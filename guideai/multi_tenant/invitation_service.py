"""PostgreSQL-backed invitation service for organization invitations.

This service handles invitation CRUD, sending via notify package,
acceptance flow, and invitation lifecycle management.

Usage:
    from guideai.multi_tenant import InvitationService

    invite_service = InvitationService(
        pool=postgres_pool,
        notify_service=notify_service,  # Optional
    )

    # Create and send invitation
    invitation = invite_service.create_invitation(
        org_id="org-123",
        request=CreateInvitationRequest(
            email="user@example.com",
            role=MemberRole.MEMBER,
        ),
        invited_by="user-456",
    )

    # Accept invitation
    membership = invite_service.accept_invitation(
        token="abc123...",
        user_id="user-789",
    )
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional, List, Dict, Any

from .contracts import (
    Invitation,
    InvitationStatus,
    InvitationChannel,
    InvitationEvent,
    InvitationWithOrg,
    InvitationListResponse,
    CreateInvitationRequest,
    AcceptInvitationRequest,
    OrgMembership,
    MemberRole,
)

if TYPE_CHECKING:
    from guideai.storage.postgres_pool import PostgresPool
    from guideai.notify import GuideAINotifyService


def _jsonb(value: Any) -> Optional[str]:
    """Serialize a value to JSON string for PostgreSQL JSONB columns."""
    if value is None:
        return None
    return json.dumps(value)


logger = logging.getLogger(__name__)


class InvitationService:
    """PostgreSQL-backed service for invitation management.

    Handles invitation creation, sending, acceptance, and lifecycle
    management with optional integration with notify package.

    Attributes:
        pool: PostgresPool instance for database operations.
        notify_service: Optional GuideAINotifyService for sending invitations.
        base_url: Base URL for invitation accept links.
    """

    DEFAULT_EXPIRATION_DAYS = 7

    def __init__(
        self,
        pool: Optional["PostgresPool"] = None,
        dsn: Optional[str] = None,
        notify_service: Optional["GuideAINotifyService"] = None,
        base_url: str = "https://guideai.dev",
    ):
        """Initialize with either a pool or DSN string.

        Args:
            pool: PostgresPool instance for database operations.
            dsn: PostgreSQL connection string (creates pool automatically).
            notify_service: Optional notification service for sending invites.
            base_url: Base URL for invitation links.

        Raises:
            ValueError: If neither pool nor dsn is provided.
        """
        if pool is not None:
            self.pool = pool
        elif dsn is not None:
            from guideai.storage.postgres_pool import PostgresPool
            self.pool = PostgresPool(dsn=dsn)
        else:
            raise ValueError("Either pool or dsn must be provided")

        self.notify_service = notify_service
        self.base_url = base_url.rstrip("/")

    # =========================================================================
    # Token Generation
    # =========================================================================

    def _generate_token(self) -> str:
        """Generate a secure invitation token.

        Returns:
            A 64-character URL-safe token.
        """
        return secrets.token_urlsafe(48)

    def _get_accept_url(self, token: str) -> str:
        """Generate the invitation acceptance URL.

        Args:
            token: Invitation token.

        Returns:
            Full URL for accepting the invitation.
        """
        return f"{self.base_url}/invitations/{token}/accept"

    # =========================================================================
    # Invitation CRUD
    # =========================================================================

    def create_invitation(
        self,
        org_id: str,
        request: CreateInvitationRequest,
        invited_by: str,
        send: bool = True,
    ) -> Invitation:
        """Create a new invitation and optionally send it.

        Args:
            org_id: Organization ID.
            request: Invitation creation request.
            invited_by: User ID sending the invitation.
            send: Whether to send the invitation via notify service.

        Returns:
            The created invitation.

        Raises:
            ValueError: If user is already a member or has pending invitation.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Check if user is already a member
            cursor.execute(
                """
                SELECT 1 FROM org_memberships om
                JOIN users u ON u.user_id = om.user_id
                WHERE om.org_id = %s AND LOWER(u.email) = LOWER(%s)
                """,
                (org_id, request.email),
            )
            if cursor.fetchone():
                raise ValueError(f"User with email {request.email} is already a member")

            # Check for existing pending invitation
            cursor.execute(
                """
                SELECT id FROM org_invitations
                WHERE org_id = %s AND LOWER(email) = LOWER(%s)
                AND status = 'pending' AND expires_at > NOW()
                """,
                (org_id, request.email),
            )
            if cursor.fetchone():
                raise ValueError(f"Pending invitation already exists for {request.email}")

            # Create invitation
            token = self._generate_token()
            expires_at = datetime.now(timezone.utc) + timedelta(days=request.expires_in_days)

            invitation = Invitation(
                org_id=org_id,
                email=request.email.lower(),
                role=request.role,
                token=token,
                channel=request.channel,
                invited_by=invited_by,
                expires_at=expires_at,
                message=request.message,
                metadata=request.metadata,
            )

            # Insert invitation
            cursor.execute(
                """
                INSERT INTO org_invitations (
                    id, org_id, email, role, status, token, channel,
                    invited_by, expires_at, message, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    invitation.id,
                    invitation.org_id,
                    invitation.email,
                    invitation.role.value,
                    invitation.status.value,
                    invitation.token,
                    invitation.channel.value,
                    invitation.invited_by,
                    invitation.expires_at,
                    invitation.message,
                    _jsonb(invitation.metadata),
                ),
            )

            # Record creation event
            self._record_event(
                cursor,
                invitation.id,
                "created",
                invited_by,
                {"channel": request.channel.value, "role": request.role.value},
            )

            conn.commit()

        logger.info(f"Created invitation {invitation.id} for {request.email} to org {org_id}")

        # Send invitation if requested and notify service available
        if send and self.notify_service and request.channel != InvitationChannel.LINK:
            self._send_invitation(invitation)

        return invitation

    def _send_invitation(self, invitation: Invitation) -> bool:
        """Send invitation via notify service.

        Args:
            invitation: Invitation to send.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self.notify_service:
            logger.warning("No notify service configured, skipping send")
            return False

        try:
            # Get organization details for the invitation
            org = self._get_org_details(invitation.org_id)
            if not org:
                logger.error(f"Organization {invitation.org_id} not found for invitation")
                return False

            accept_url = self._get_accept_url(invitation.token)

            # Map invitation channel to notify channel
            from notify import Channel, Recipient

            channel_map = {
                InvitationChannel.EMAIL: Channel.EMAIL,
                InvitationChannel.SLACK: Channel.SLACK,
                InvitationChannel.SMS: Channel.SMS,
            }

            notify_channel = channel_map.get(invitation.channel)
            if not notify_channel:
                logger.warning(f"Channel {invitation.channel} not supported for sending")
                return False

            recipient = Recipient(
                id=invitation.email,
                email=invitation.email if notify_channel == Channel.EMAIL else None,
                phone=invitation.metadata.get("phone") if notify_channel == Channel.SMS else None,
                slack_user_id=invitation.metadata.get("slack_user_id") if notify_channel == Channel.SLACK else None,
            )

            # Send using template
            import asyncio
            result = asyncio.run(
                self.notify_service.send_with_template(
                    template_name="organization_invitation",
                    context={
                        "org_name": org["name"],
                        "inviter_name": invitation.metadata.get("inviter_name", "A team member"),
                        "role": invitation.role.value,
                        "accept_url": accept_url,
                        "expires_in_days": (invitation.expires_at - datetime.now(timezone.utc)).days,
                        "message": invitation.message,
                    },
                    recipients=[recipient],
                    channel=notify_channel,
                )
            )

            if result.successful_count > 0:
                # Record sent event
                with self.pool.connection() as conn:
                    cursor = conn.cursor()
                    self._record_event(
                        cursor,
                        invitation.id,
                        "sent",
                        invitation.invited_by,
                        {"channel": invitation.channel.value},
                    )
                    conn.commit()

                logger.info(f"Sent invitation {invitation.id} via {invitation.channel.value}")
                return True
            else:
                logger.error(f"Failed to send invitation {invitation.id}")
                return False

        except Exception as e:
            logger.exception(f"Error sending invitation {invitation.id}: {e}")
            return False

    def _get_org_details(self, org_id: str) -> Optional[Dict[str, Any]]:
        """Get organization details for invitation.

        Args:
            org_id: Organization ID.

        Returns:
            Dict with org details or None if not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, slug, display_name FROM organizations WHERE id = %s",
                (org_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return {
            "name": row[0],
            "slug": row[1],
            "display_name": row[2],
        }

    def get_invitation(self, invitation_id: str) -> Optional[Invitation]:
        """Get an invitation by ID.

        Args:
            invitation_id: Invitation ID.

        Returns:
            The invitation if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, org_id, email, role, status, token, channel,
                       invited_by, expires_at, accepted_at, accepted_by,
                       message, metadata, created_at, updated_at
                FROM org_invitations
                WHERE id = %s
                """,
                (invitation_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return self._row_to_invitation(row)

    def get_invitation_by_token(self, token: str) -> Optional[InvitationWithOrg]:
        """Get an invitation by token with organization details.

        Args:
            token: Invitation token.

        Returns:
            InvitationWithOrg if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT i.id, i.org_id, i.email, i.role, i.status, i.token, i.channel,
                       i.invited_by, i.expires_at, i.accepted_at, i.accepted_by,
                       i.message, i.metadata, i.created_at, i.updated_at,
                       o.name, o.slug,
                       u.display_name as inviter_name
                FROM org_invitations i
                JOIN organizations o ON o.id = i.org_id
                LEFT JOIN users u ON u.user_id = i.invited_by
                WHERE i.token = %s
                """,
                (token,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        invitation = self._row_to_invitation(row[:15])

        # Record view event if pending
        if invitation.status == InvitationStatus.PENDING:
            cursor = conn.cursor()
            self._record_event(cursor, invitation.id, "viewed", None, {})
            conn.commit()

        return InvitationWithOrg(
            invitation=invitation,
            org_name=row[15],
            org_slug=row[16],
            inviter_name=row[17],
        )

    def list_org_invitations(
        self,
        org_id: str,
        status: Optional[InvitationStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> InvitationListResponse:
        """List invitations for an organization.

        Args:
            org_id: Organization ID.
            status: Optional status filter.
            limit: Maximum results to return.
            offset: Pagination offset.

        Returns:
            InvitationListResponse with invitations and counts.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Build query with optional status filter
            where_clause = "WHERE org_id = %s"
            params: List[Any] = [org_id]

            if status:
                where_clause += " AND status = %s"
                params.append(status.value)

            # Get total count
            cursor.execute(
                f"SELECT COUNT(*) FROM org_invitations {where_clause}",
                tuple(params),
            )
            total = cursor.fetchone()[0]

            # Get pending count
            cursor.execute(
                """
                SELECT COUNT(*) FROM org_invitations
                WHERE org_id = %s AND status = 'pending' AND expires_at > NOW()
                """,
                (org_id,),
            )
            pending_count = cursor.fetchone()[0]

            # Get invitations
            cursor.execute(
                f"""
                SELECT id, org_id, email, role, status, token, channel,
                       invited_by, expires_at, accepted_at, accepted_by,
                       message, metadata, created_at, updated_at
                FROM org_invitations
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params) + (limit, offset),
            )
            rows = cursor.fetchall()

        invitations = [self._row_to_invitation(row) for row in rows]

        return InvitationListResponse(
            invitations=invitations,
            total=total,
            pending_count=pending_count,
        )

    def _row_to_invitation(self, row: tuple) -> Invitation:
        """Convert a database row to an Invitation object.

        Args:
            row: Database row tuple.

        Returns:
            Invitation object.
        """
        return Invitation(
            id=row[0],
            org_id=row[1],
            email=row[2],
            role=MemberRole(row[3]),
            status=InvitationStatus(row[4]),
            token=row[5],
            channel=InvitationChannel(row[6]),
            invited_by=row[7],
            expires_at=row[8],
            accepted_at=row[9],
            accepted_by=row[10],
            message=row[11],
            metadata=row[12] or {},
            created_at=row[13],
            updated_at=row[14],
        )

    # =========================================================================
    # Invitation Acceptance
    # =========================================================================

    def accept_invitation(
        self,
        token: str,
        user_id: str,
    ) -> OrgMembership:
        """Accept an invitation and create membership.

        Args:
            token: Invitation token.
            user_id: User ID accepting the invitation.

        Returns:
            The created OrgMembership.

        Raises:
            ValueError: If invitation is invalid, expired, or user email doesn't match.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Get invitation
            cursor.execute(
                """
                SELECT id, org_id, email, role, status, expires_at
                FROM org_invitations
                WHERE token = %s
                FOR UPDATE
                """,
                (token,),
            )
            row = cursor.fetchone()

            if not row:
                raise ValueError("Invalid invitation token")

            inv_id, org_id, email, role, status, expires_at = row

            if status != "pending":
                raise ValueError(f"Invitation is no longer pending (status: {status})")

            if expires_at < datetime.now(timezone.utc):
                # Mark as expired
                cursor.execute(
                    "UPDATE org_invitations SET status = 'expired', updated_at = NOW() WHERE id = %s",
                    (inv_id,),
                )
                conn.commit()
                raise ValueError("Invitation has expired")

            # Verify user email matches invitation
            cursor.execute(
                "SELECT email FROM users WHERE user_id = %s",
                (user_id,),
            )
            user_row = cursor.fetchone()
            if not user_row:
                raise ValueError("User not found")

            if user_row[0].lower() != email.lower():
                raise ValueError("User email does not match invitation email")

            # Check if already a member
            cursor.execute(
                "SELECT 1 FROM org_memberships WHERE org_id = %s AND user_id = %s",
                (org_id, user_id),
            )
            if cursor.fetchone():
                raise ValueError("User is already a member of this organization")

            # Create membership
            import uuid
            membership_id = f"mem-{uuid.uuid4().hex[:12]}"

            cursor.execute(
                """
                INSERT INTO org_memberships (membership_id, org_id, user_id, role, invited_by, invited_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    membership_id,
                    org_id,
                    user_id,
                    role,
                    inv_id,  # Store invitation reference
                    datetime.now(timezone.utc),
                ),
            )

            # Update invitation
            cursor.execute(
                """
                UPDATE org_invitations
                SET status = 'accepted', accepted_at = NOW(), accepted_by = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (user_id, inv_id),
            )

            # Record acceptance event
            self._record_event(cursor, inv_id, "accepted", user_id, {"membership_id": membership_id})

            conn.commit()

        logger.info(f"User {user_id} accepted invitation {inv_id} to org {org_id}")

        return OrgMembership(
            id=membership_id,
            org_id=org_id,
            user_id=user_id,
            role=MemberRole(role),
            invited_by=inv_id,
            invited_at=datetime.now(timezone.utc),
        )

    # =========================================================================
    # Invitation Management
    # =========================================================================

    def revoke_invitation(
        self,
        invitation_id: str,
        revoked_by: str,
    ) -> bool:
        """Revoke a pending invitation.

        Args:
            invitation_id: Invitation ID.
            revoked_by: User ID revoking the invitation.

        Returns:
            True if revoked, False if not found or not pending.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE org_invitations
                SET status = 'revoked', updated_at = NOW()
                WHERE id = %s AND status = 'pending'
                RETURNING id
                """,
                (invitation_id,),
            )

            result = cursor.fetchone()

            if result:
                self._record_event(cursor, invitation_id, "revoked", revoked_by, {})
                conn.commit()
                logger.info(f"Invitation {invitation_id} revoked by {revoked_by}")
                return True

            return False

    def resend_invitation(
        self,
        invitation_id: str,
        resent_by: str,
    ) -> bool:
        """Resend a pending invitation.

        Args:
            invitation_id: Invitation ID.
            resent_by: User ID resending the invitation.

        Returns:
            True if resent, False if not found or not pending.
        """
        invitation = self.get_invitation(invitation_id)
        if not invitation or invitation.status != InvitationStatus.PENDING:
            return False

        if invitation.channel == InvitationChannel.LINK:
            return False  # Can't resend copy-link invitations

        success = self._send_invitation(invitation)

        if success:
            with self.pool.connection() as conn:
                cursor = conn.cursor()
                self._record_event(cursor, invitation_id, "resent", resent_by, {})
                conn.commit()

        return success

    def expire_invitations(self) -> int:
        """Expire all past-due invitations.

        This should be called periodically (e.g., via cron or scheduler).

        Returns:
            Number of invitations expired.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE org_invitations
                SET status = 'expired', updated_at = NOW()
                WHERE status = 'pending' AND expires_at < NOW()
                RETURNING id
                """
            )

            expired_ids = [row[0] for row in cursor.fetchall()]

            for inv_id in expired_ids:
                self._record_event(cursor, inv_id, "expired", None, {"auto_expired": True})

            conn.commit()

        if expired_ids:
            logger.info(f"Expired {len(expired_ids)} invitations")

        return len(expired_ids)

    def get_invitation_link(self, invitation_id: str) -> Optional[str]:
        """Get the accept URL for an invitation.

        Args:
            invitation_id: Invitation ID.

        Returns:
            Accept URL or None if not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT token FROM org_invitations WHERE id = %s AND status = 'pending'",
                (invitation_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return self._get_accept_url(row[0])

    # =========================================================================
    # Event Recording
    # =========================================================================

    def _record_event(
        self,
        cursor,
        invitation_id: str,
        event_type: str,
        actor_id: Optional[str],
        metadata: Dict[str, Any],
    ) -> None:
        """Record an invitation lifecycle event.

        Args:
            cursor: Database cursor.
            invitation_id: Invitation ID.
            event_type: Type of event.
            actor_id: User who triggered the event.
            metadata: Additional event metadata.
        """
        import uuid
        event_id = f"iev-{uuid.uuid4().hex[:12]}"

        cursor.execute(
            """
            INSERT INTO invitation_events (id, invitation_id, event_type, actor_id, metadata)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (event_id, invitation_id, event_type, actor_id, _jsonb(metadata)),
        )

    def get_invitation_events(self, invitation_id: str) -> List[InvitationEvent]:
        """Get all events for an invitation.

        Args:
            invitation_id: Invitation ID.

        Returns:
            List of InvitationEvent objects.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, invitation_id, event_type, actor_id, metadata, created_at
                FROM invitation_events
                WHERE invitation_id = %s
                ORDER BY created_at ASC
                """,
                (invitation_id,),
            )
            rows = cursor.fetchall()

        return [
            InvitationEvent(
                id=row[0],
                invitation_id=row[1],
                event_type=row[2],
                actor_id=row[3],
                metadata=row[4] or {},
                created_at=row[5],
            )
            for row in rows
        ]

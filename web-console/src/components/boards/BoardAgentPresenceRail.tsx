/**
 * BoardAgentPresenceRail
 *
 * Compact board-chrome element showing project participants at a glance.
 * Placed directly below BoardFilterBar.
 *
 * Left cluster: label + summary line
 * Middle cluster: compact roster of avatars
 * Right cluster: "View all" button
 *
 * Following COLLAB_SAAS_REQUIREMENTS.md (Student):
 *   GPU-only motion, no shadows, glassmorphic flat surface.
 */

import React from 'react';
import { ActorAvatar } from '../actors/ActorAvatar';
import type { BoardParticipant, BoardParticipantSummary } from './boardParticipants';
import { rankBoardParticipants } from './boardParticipants';
import './BoardAgentPresenceRail.css';

export interface BoardAgentPresenceRailProps {
  participants: BoardParticipant[];
  summary: BoardParticipantSummary;
  onViewAll: () => void;
  onParticipantClick?: (participant: BoardParticipant) => void;
}

const MAX_INLINE = 6;

function formatParticipantSummary(summary: BoardParticipantSummary): string {
  const parts = [`${summary.total} members`];
  if (summary.humans > 0) parts.push(`${summary.humans} people`);
  if (summary.agents > 0) parts.push(`${summary.agents} agents`);
  return parts.join(' · ');
}

function participantTooltip(participant: BoardParticipant): string {
  const secondary = participant.kind === 'agent'
    ? (participant.statusLine ?? participant.actor.presenceLabel)
    : (participant.roleLabel ?? participant.statusLine ?? 'Project member');
  return `${participant.actor.displayName} • ${secondary}`;
}

export const BoardAgentPresenceRail: React.FC<BoardAgentPresenceRailProps> = ({
  participants,
  summary,
  onViewAll,
  onParticipantClick,
}) => {
  if (summary.total === 0) return null;

  const ranked = rankBoardParticipants(participants);
  const visible = ranked.slice(0, MAX_INLINE);
  const overflow = summary.total - visible.length;

  return (
    <div
      className="board-agent-presence-rail animate-fade-in-up"
      role="region"
      aria-label="Project members"
    >
      <div className="presence-rail-summary">
        <span className="presence-rail-label">Project members</span>
        <span className="presence-rail-line">{formatParticipantSummary(summary)}</span>
      </div>

      <div className="presence-rail-roster" role="list" aria-label="Project member roster">
        {visible.map((participant) => (
          <button
            key={participant.id}
            type="button"
            className={`presence-rail-avatar-button pressable${participant.isCurrentUser ? ' presence-rail-avatar-button-current' : ''}`}
            onClick={() => onParticipantClick?.(participant)}
            aria-label={`${participant.actor.displayName} – ${participant.kind === 'agent' ? participant.actor.presenceLabel : participant.roleLabel ?? 'Project member'}`}
            title={participantTooltip(participant)}
            data-tooltip={participantTooltip(participant)}
            data-haptic="light"
          >
            <ActorAvatar
              actor={participant.actor}
              size="sm"
              decorative
              showPresenceDot={participant.kind === 'agent'}
              surfaceType="badge"
            />
            {participant.isCurrentUser ? <span className="presence-rail-you-pill">You</span> : null}
            <span className="presence-rail-avatar-label">{participant.actor.displayName}</span>
          </button>
        ))}
        {overflow > 0 && (
          <button
            type="button"
            className="presence-rail-overflow pressable"
            onClick={onViewAll}
            aria-label={`View ${overflow} more members`}
            data-haptic="light"
          >
            +{overflow}
          </button>
        )}
      </div>

      <div className="presence-rail-actions">
        <button
          type="button"
          className="presence-rail-view-all pressable"
          onClick={onViewAll}
          data-haptic="light"
        >
          View all
        </button>
      </div>
    </div>
  );
};

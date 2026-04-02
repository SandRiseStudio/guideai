/**
 * ChatHub — floating avatar cluster anchored to bottom-right of the board.
 *
 * Shows all project participants as a horizontal row of avatars.
 * Clicking any avatar or the overflow chip opens the full presence/collab drawer.
 * Minimal placeholder — will evolve into chat/DM hub in the future.
 *
 * In board mode, also shows connection status (Live/reconnecting/etc).
 */

import { memo } from 'react';
import { ActorAvatar } from '../actors/ActorAvatar';
import { rankBoardParticipants, type BoardParticipant } from './boardParticipants';
import './ChatHub.css';

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

export interface ChatHubProps {
  participants: BoardParticipant[];
  onOpen: () => void;
  onParticipantClick?: (participant: BoardParticipant) => void;
  /** Maximum avatars to show before overflow chip */
  maxVisible?: number;
  /** Connection state for real-time collab */
  connectionState?: ConnectionState;
}

const DEFAULT_MAX_VISIBLE = 24;

export const ChatHub = memo(function ChatHub({
  participants,
  onOpen,
  onParticipantClick,
  maxVisible = DEFAULT_MAX_VISIBLE,
  connectionState,
}: ChatHubProps) {
  if (participants.length === 0 && !connectionState) return null;

  const ranked = rankBoardParticipants(participants);
  const visible = ranked.slice(0, maxVisible);
  const overflow = participants.length - visible.length;

  const connectionLabel =
    connectionState === 'connected'
      ? 'Live'
      : connectionState === 'reconnecting'
      ? 'Reconnecting'
      : connectionState === 'connecting'
      ? 'Connecting'
      : connectionState === 'disconnected'
      ? 'Offline'
      : null;

  return (
    <div className="chathub" role="region" aria-label="Project members">
      {connectionState && (
        <div
          className={`chathub-connection chathub-connection-${connectionState}`}
          aria-live="polite"
          aria-label={`Connection status: ${connectionLabel}`}
        >
          <span className="chathub-connection-dot" />
          <span className="chathub-connection-label">{connectionLabel}</span>
        </div>
      )}
      {participants.length > 0 && (
        <div className="chathub-avatars" role="list">
          {visible.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`chathub-avatar pressable${p.isCurrentUser ? ' chathub-avatar-you' : ''}`}
              onClick={() => (onParticipantClick ? onParticipantClick(p) : onOpen())}
              aria-label={`${p.actor.displayName} – ${p.kind === 'agent' ? 'Agent' : 'Person'}`}
              title={p.actor.displayName}
              data-haptic="light"
              role="listitem"
            >
              <ActorAvatar
                actor={p.actor}
                size="sm"
                decorative
                showPresenceDot={p.kind === 'agent'}
                surfaceType="badge"
              />
            </button>
          ))}
          {overflow > 0 && (
            <button
              type="button"
              className="chathub-overflow pressable"
              onClick={onOpen}
              aria-label={`View ${overflow} more members`}
              title={`${overflow} more members`}
              data-haptic="light"
            >
              +{overflow}
            </button>
          )}
        </div>
      )}
    </div>
  );
});

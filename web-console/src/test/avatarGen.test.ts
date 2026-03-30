import { describe, expect, it } from 'vitest';
import { generateAvatarVariant } from '../utils/avatarGen';

describe('generateAvatarVariant', () => {
  it('is deterministic for the same seed and style version', () => {
    expect(generateAvatarVariant('agent:1:Code Bot', 'agent', 1)).toEqual(
      generateAvatarVariant('agent:1:Code Bot', 'agent', 1),
    );
  });

  it('changes when the seed changes', () => {
    expect(generateAvatarVariant('agent:1:Code Bot', 'agent', 1)).not.toEqual(
      generateAvatarVariant('agent:2:Code Bot', 'agent', 1),
    );
  });

  it('pins service actors to the antenna accessory', () => {
    expect(generateAvatarVariant('svc:1', 'service', 1).accessory).toBe('antenna');
  });
});

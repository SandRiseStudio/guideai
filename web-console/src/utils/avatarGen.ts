import type { ActorAvatarVariant, ActorKind, AvatarPalette } from '../types/actor';

const PALETTES: Array<{ id: string; value: AvatarPalette }> = [
  {
    id: 'sea-glass',
    value: {
      surface: '#d9efe9',
      shell: '#2f8074',
      shellMuted: '#8ab8ae',
      face: '#f2d7b1',
      hair: '#324b54',
      accent: '#e67e22',
      accentMuted: '#f2b36d',
      line: '#193238',
    },
  },
  {
    id: 'copper-sand',
    value: {
      surface: '#efe2d0',
      shell: '#9f5f37',
      shellMuted: '#d4b395',
      face: '#f3d4b3',
      hair: '#56352a',
      accent: '#1f8a70',
      accentMuted: '#7bc7b6',
      line: '#33221d',
    },
  },
  {
    id: 'night-mint',
    value: {
      surface: '#dbe8e2',
      shell: '#31545c',
      shellMuted: '#86a2a4',
      face: '#eec4a2',
      hair: '#162d33',
      accent: '#c96a2b',
      accentMuted: '#e3ad79',
      line: '#102126',
    },
  },
  {
    id: 'paper-olive',
    value: {
      surface: '#e8ead6',
      shell: '#5d6f3f',
      shellMuted: '#b0ba8b',
      face: '#f2d7bc',
      hair: '#4b4030',
      accent: '#0f7c8a',
      accentMuted: '#71b8c0',
      line: '#2b3021',
    },
  },
  {
    id: 'clay-sky',
    value: {
      surface: '#e7e3dc',
      shell: '#496a7c',
      shellMuted: '#9fb4c1',
      face: '#f1cfaa',
      hair: '#5c4738',
      accent: '#c75f32',
      accentMuted: '#e2a081',
      line: '#22323d',
    },
  },
];

const ACCESSORIES: ActorAvatarVariant['accessory'][] = ['none', 'visor', 'headband', 'badge', 'antenna'];
const EYES: ActorAvatarVariant['eyeShape'][] = ['dot', 'bar', 'wide'];
const MOUTHS: ActorAvatarVariant['mouthShape'][] = ['flat', 'smile', 'focus'];
const SHAPES: ActorAvatarVariant['shellShape'][] = ['round', 'squircle'];
const SCENE_ACCENTS: ActorAvatarVariant['sceneAccent'][] = ['desk', 'idle', 'sleep'];

function hashValue(seed: string): number {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function pick<T>(items: T[], hash: number, shift: number): T {
  return items[(hash >>> shift) % items.length]!;
}

export function generateAvatarVariant(
  seed: string,
  kind: ActorKind,
  styleVersion = 1,
): ActorAvatarVariant {
  const hash = hashValue(`${styleVersion}:${kind}:${seed}`);
  const palette = pick(PALETTES, hash, 1);
  const accessory = kind === 'service' ? 'antenna' : pick(ACCESSORIES, hash, 6);
  const sceneAccent: ActorAvatarVariant['sceneAccent'] =
    kind === 'human'
      ? pick(['desk', 'idle'] as const, hash, 11)
      : pick(SCENE_ACCENTS, hash, 11);

  return {
    paletteId: palette.id,
    palette: palette.value,
    accessory,
    eyeShape: pick(EYES, hash, 13),
    mouthShape: pick(MOUTHS, hash, 17),
    shellShape: pick(SHAPES, hash, 21),
    spriteSeed: hash,
    sceneAccent,
  };
}

export type ActorKind = 'human' | 'agent' | 'service';
export type ActorPresenceState = 'available' | 'working' | 'finished_recently' | 'paused' | 'offline' | 'at_capacity';

interface AvatarPalette {
	surface: string;
	shell: string;
	shellMuted: string;
	face: string;
	hair: string;
	accent: string;
	accentMuted: string;
	line: string;
}

interface ActorAvatarVariant {
	palette: AvatarPalette;
	accessory: 'none' | 'visor' | 'headband' | 'badge' | 'antenna';
	eyeShape: 'dot' | 'bar' | 'wide';
	mouthShape: 'flat' | 'smile' | 'focus';
	shellShape: 'round' | 'squircle';
}

export interface ActorViewModel {
	id: string;
	kind: ActorKind;
	displayName: string;
	subtitle?: string;
	avatarSeed: string;
	avatarStyleVersion: number;
	presenceState: ActorPresenceState;
	presenceLabel: string;
	statusAccent: string;
	avatarVariant: ActorAvatarVariant;
}

const PRESENCE_LABELS: Record<ActorPresenceState, string> = {
	available: 'Available',
	working: 'Working',
	finished_recently: 'Finished recently',
	paused: 'Paused',
	offline: 'Offline',
	at_capacity: 'At capacity',
};

const PRESENCE_ACCENTS: Record<ActorPresenceState, string> = {
	available: '#1f8a70',
	working: '#0f7c8a',
	finished_recently: '#5aa08c',
	paused: '#e49d37',
	offline: '#8c9399',
	at_capacity: '#d27c2c',
};

const PALETTES: AvatarPalette[] = [
	{ surface: '#d9efe9', shell: '#2f8074', shellMuted: '#8ab8ae', face: '#f2d7b1', hair: '#324b54', accent: '#e67e22', accentMuted: '#f2b36d', line: '#193238' },
	{ surface: '#efe2d0', shell: '#9f5f37', shellMuted: '#d4b395', face: '#f3d4b3', hair: '#56352a', accent: '#1f8a70', accentMuted: '#7bc7b6', line: '#33221d' },
	{ surface: '#dbe8e2', shell: '#31545c', shellMuted: '#86a2a4', face: '#eec4a2', hair: '#162d33', accent: '#c96a2b', accentMuted: '#e3ad79', line: '#102126' },
	{ surface: '#e8ead6', shell: '#5d6f3f', shellMuted: '#b0ba8b', face: '#f2d7bc', hair: '#4b4030', accent: '#0f7c8a', accentMuted: '#71b8c0', line: '#2b3021' },
	{ surface: '#e7e3dc', shell: '#496a7c', shellMuted: '#9fb4c1', face: '#f1cfaa', hair: '#5c4738', accent: '#c75f32', accentMuted: '#e2a081', line: '#22323d' },
];

function hashValue(seed: string): number {
	let hash = 2166136261;
	for (let index = 0; index < seed.length; index += 1) {
		hash ^= seed.charCodeAt(index);
		hash = Math.imul(hash, 16777619);
	}
	return hash >>> 0;
}

function pick<T>(items: readonly T[], hash: number, shift: number): T {
	return items[(hash >>> shift) % items.length]!;
}

function generateAvatarVariant(seed: string, kind: ActorKind, styleVersion = 1): ActorAvatarVariant {
	const hash = hashValue(`${styleVersion}:${kind}:${seed}`);
	return {
		palette: pick(PALETTES, hash, 1),
		accessory: kind === 'service' ? 'antenna' : pick(['none', 'visor', 'headband', 'badge', 'antenna'] as const, hash, 6),
		eyeShape: pick(['dot', 'bar', 'wide'] as const, hash, 13),
		mouthShape: pick(['flat', 'smile', 'focus'] as const, hash, 17),
		shellShape: pick(['round', 'squircle'] as const, hash, 21),
	};
}

export function createActorViewModel(input: {
	id: string;
	kind: ActorKind;
	displayName: string;
	subtitle?: string;
	avatarSeed?: string;
	avatarStyleVersion?: number;
	presenceState?: ActorPresenceState;
}): ActorViewModel {
	const avatarStyleVersion = input.avatarStyleVersion ?? 1;
	const avatarSeed = input.avatarSeed ?? `${input.kind}:${input.id}:${input.displayName}`;
	const presenceState = input.presenceState ?? 'available';
	return {
		id: input.id,
		kind: input.kind,
		displayName: input.displayName,
		subtitle: input.subtitle,
		avatarSeed,
		avatarStyleVersion,
		presenceState,
		presenceLabel: PRESENCE_LABELS[presenceState],
		statusAccent: PRESENCE_ACCENTS[presenceState],
		avatarVariant: generateAvatarVariant(avatarSeed, input.kind, avatarStyleVersion),
	};
}

export function buildActorAvatarSvg(actor: ActorViewModel, size = 40): string {
	const variant = actor.avatarVariant;
	const radius = variant.shellShape === 'round' ? size / 2 : Math.round(size * 0.34);
	const eyeWidth = variant.eyeShape === 'bar' ? 4 : variant.eyeShape === 'wide' ? 5 : 3;
	const eyeHeight = variant.eyeShape === 'bar' ? 1.6 : 3;
	const mouth = variant.mouthShape === 'focus'
		? `<circle cx="${size * 0.5}" cy="${size * 0.64}" r="${size * 0.05}" fill="none" stroke="${variant.palette.line}" stroke-width="1.8" />`
		: variant.mouthShape === 'flat'
			? `<rect x="${size * 0.4}" y="${size * 0.63}" width="${size * 0.2}" height="1.8" rx="0.9" fill="${variant.palette.line}" />`
			: `<path d="M ${size * 0.39} ${size * 0.62} Q ${size * 0.5} ${size * 0.69} ${size * 0.61} ${size * 0.62}" fill="none" stroke="${variant.palette.line}" stroke-width="1.8" stroke-linecap="round" />`;
	const accessory = variant.accessory === 'visor'
		? `<rect x="${size * 0.22}" y="${size * 0.34}" width="${size * 0.56}" height="${size * 0.09}" rx="${size * 0.045}" fill="${variant.palette.accent}" fill-opacity="0.92" />`
		: variant.accessory === 'headband'
			? `<rect x="${size * 0.14}" y="${size * 0.18}" width="${size * 0.72}" height="${size * 0.07}" rx="${size * 0.035}" fill="${variant.palette.accent}" />`
			: variant.accessory === 'badge'
				? `<circle cx="${size * 0.78}" cy="${size * 0.78}" r="${size * 0.09}" fill="${variant.palette.accent}" stroke="${variant.palette.line}" stroke-opacity="0.18" stroke-width="1.5" />`
				: variant.accessory === 'antenna'
					? `<path d="M ${size * 0.5} ${size * 0.06} L ${size * 0.5} ${size * 0.18}" stroke="${variant.palette.accent}" stroke-width="2" stroke-linecap="round" /><circle cx="${size * 0.5}" cy="${size * 0.05}" r="${size * 0.05}" fill="${variant.palette.accent}" />`
					: '';

	return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" fill="none">
		<rect width="${size}" height="${size}" rx="${radius}" fill="${variant.palette.surface}" />
		<rect x="${size * 0.22}" y="${size * 0.66}" width="${size * 0.56}" height="${size * 0.24}" rx="${size * 0.12}" fill="${variant.palette.shell}" />
		<rect x="${size * 0.24}" y="${size * 0.18}" width="${size * 0.52}" height="${size * 0.5}" rx="${size * 0.18}" fill="${variant.palette.face}" stroke="${variant.palette.line}" stroke-opacity="0.12" stroke-width="1.5" />
		<rect x="${size * 0.24}" y="${size * 0.18}" width="${size * 0.52}" height="${size * 0.17}" rx="${size * 0.14}" fill="${variant.palette.hair}" />
		<rect x="${size * 0.36}" y="${size * 0.46}" width="${eyeWidth}" height="${eyeHeight}" rx="${eyeHeight / 2}" fill="${variant.palette.line}" />
		<rect x="${size * 0.58}" y="${size * 0.46}" width="${eyeWidth}" height="${eyeHeight}" rx="${eyeHeight / 2}" fill="${variant.palette.line}" />
		${mouth}
		${accessory}
		<circle cx="${size - 6}" cy="${size - 6}" r="5" fill="${actor.statusAccent}" stroke="${variant.palette.surface}" stroke-width="2" />
	</svg>`;
}

export function buildActorAvatarDataUri(actor: ActorViewModel, size = 40): string {
	return `data:image/svg+xml;utf8,${encodeURIComponent(buildActorAvatarSvg(actor, size))}`;
}

export function buildActorAvatarHtml(actor: ActorViewModel, size = 44): string {
	const dataUri = buildActorAvatarDataUri(actor, size);
	return `<span style="display:inline-flex;align-items:center;justify-content:center;width:${size}px;height:${size}px;border-radius:${Math.round(size * 0.34)}px;overflow:hidden;border:1px solid color-mix(in srgb, ${actor.avatarVariant.palette.line} 18%, transparent);background:${actor.avatarVariant.palette.surface};">
		<img src="${dataUri}" alt="" width="${size}" height="${size}" style="display:block;width:${size}px;height:${size}px;" />
	</span>`;
}

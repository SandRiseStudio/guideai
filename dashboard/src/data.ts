export interface ProgressItem {
  workItem: string;
  owner: string;
  status: string;
  evidence: string;
  section: string;
}

export interface TimelineEntry {
  order: string;
  artifact: string;
  description: string;
  date: string;
}

export interface AlignmentEntry {
  text: string;
}

export interface ConsentMetric {
  surface: string;
  prompts: number;
  approvals: number;
  denials: number;
  snoozes: number;
  mfaRequired: number;
  mfaCompleted: number;
  averageLatencySeconds: number;
  p95LatencySeconds: number;
}

export interface ConsentSnapshot {
  metrics: ConsentMetric[];
  updated: string;
}

const tableSectionRegex = /##\s+([^\n]+)\n([\s\S]*?)(?=\n##\s+|\n_Last updated|$)/g;

function parseTableBlock(block: string): string[][] {
  const lines = block
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('|'));

  if (lines.length <= 2) return [];

  const dataLines = lines.slice(2);

  return dataLines
    .map((line) =>
      line
        .split('|')
        .map((cell) => cell.trim())
        .filter(Boolean)
    )
    .filter((row) => row.length > 0);
}

export function parseProgressTracker(markdown: string): {
  sections: ProgressItem[];
  lastUpdated: string;
} {
  tableSectionRegex.lastIndex = 0;
  const sections: ProgressItem[] = [];
  let match: RegExpExecArray | null;

  while ((match = tableSectionRegex.exec(markdown)) !== null) {
    const [, sectionTitle, block] = match;
    const rows = parseTableBlock(block);

    rows.forEach((row) => {
      const [workItem = '', owner = '', status = '', evidence = ''] = row;
      sections.push({
        workItem,
        owner,
        status,
        evidence,
        section: sectionTitle.trim(),
      });
    });
  }

  const lastUpdatedMatch = markdown.match(/_Last updated: (.+?)_/);

  return {
    sections,
    lastUpdated: lastUpdatedMatch ? lastUpdatedMatch[1] : 'Unknown',
  };
}

export function parseBuildTimeline(markdown: string): TimelineEntry[] {
  const rows = parseTableBlock(markdown);
  return rows.map(([order = '', artifact = '', description = '', date = '']) => ({
    order,
    artifact,
    description,
    date,
  }));
}

export function parseAlignmentLog(markdown: string): AlignmentEntry[] {
  const listRegex = /^-\s+(.+)$/gm;
  const entries: AlignmentEntry[] = [];
  let match: RegExpExecArray | null;

  while ((match = listRegex.exec(markdown)) !== null) {
    entries.push({ text: match[1].trim() });
  }

  return entries;
}

export function parseConsentSnapshot(markdown: string): ConsentSnapshot {
  const rows = parseTableBlock(markdown);
  const metrics: ConsentMetric[] = rows.map((row) => {
    const [
      surface = '',
      prompts = '0',
      approvals = '0',
      denials = '0',
      snoozes = '0',
      mfaRequired = '0',
      mfaCompleted = '0',
      avgLatency = '0',
      p95Latency = '0',
    ] = row;

    return {
      surface,
      prompts: Number(prompts),
      approvals: Number(approvals),
      denials: Number(denials),
      snoozes: Number(snoozes),
      mfaRequired: Number(mfaRequired),
      mfaCompleted: Number(mfaCompleted),
      averageLatencySeconds: Number(avgLatency),
      p95LatencySeconds: Number(p95Latency),
    };
  });

  const updatedMatch = markdown.match(/_Updated:\s*([^_]+)_/i);

  return {
    metrics,
    updated: updatedMatch ? updatedMatch[1].trim() : 'Unknown',
  };
}

/** A small, fixed set of reflection prompts for the new-entry form's
 * "Need inspiration?" control (see NewEntryForm.tsx) - not stored or
 * customizable, just static copy living in the codebase. Specific to a
 * music-and-memories journal rather than generic journaling prompts, in
 * the same warm, direct, second-person voice as the rest of this app's
 * copy (e.g. NewEntryForm's own textarea placeholder, or
 * AccountSettings.tsx's account-deletion copy). A prompt is shown
 * alongside the journal text field as something to read and respond to
 * in your own words - it's never inserted into the textarea itself. */
export const ENTRY_PROMPTS: readonly string[] = [
  "What were you doing right before you hit play on this?",
  "Who's in this memory with you?",
  'What line or moment in this playlist hits hardest?',
  'Where were you when this became the soundtrack?',
  'What did the first song make you picture, the moment it started?',
  "How would you explain this playlist to someone who wasn't there?",
  "What's something about this memory you haven't told anyone?",
  "Was there a moment you wanted to skip - and didn't?",
  'What do you want to remember about today, five years from now?',
  'Which song here would you play for someone, just to help them understand?',
  'What was the weather like, in this memory?',
  'Did this playlist make the moment, or did the moment make the playlist?',
  'Is there a smell or taste that belongs in this memory too?',
  'Who would be surprised this song means this much to you?',
  'What were you hoping would happen, right when you pressed play?',
  "Is there a lyric here that says something you couldn't?",
  "If this playlist were the soundtrack to a scene, what's happening in it?",
  "What's different about you now, compared to whoever first heard this?",
  'If this memory had a one-line title, what would it be?',
  'Which song here surprised you by how well it fit?',
] as const

/** A random prompt, distinct from `exclude` when possible (so repeatedly
 * clicking "Try another" always visibly cycles rather than sometimes
 * silently re-showing the same one). Falls back to allowing a repeat
 * only if the whole list were ever trimmed down to a single prompt. */
export function getRandomPrompt(exclude?: string | null): string {
  const pool = exclude !== undefined && exclude !== null ? ENTRY_PROMPTS.filter((p) => p !== exclude) : ENTRY_PROMPTS
  const candidates = pool.length > 0 ? pool : ENTRY_PROMPTS
  return candidates[Math.floor(Math.random() * candidates.length)]
}

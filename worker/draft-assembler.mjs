// draft-assembler: hook file + lead config in, staged outreach + tell-scan out.
// Pure Node, no DOM. Rule-based only: no judgment, no sending, no network.
// Usage: node worker-draft-assembler.mjs <hook.md> <lead.json> [out.md]
import { readFileSync, writeFileSync } from "fs";

const TELLS = {
  emDash: /—/g,
  bannedWords: /\b(delve|tapestry|landscape|realm|elevate|leverage|showcase|robust|seamless|cutting-edge|game-changer|passionate|furthermore|moreover|additionally|in conclusion|overall,|it's important to note|it's worth mentioning|in today's fast-paced|gone are the days)\b/gi,
  triplets: /(\b\w+\b,\s+\b\w+\b,\s+and\s+\b\w+\b)/g,
  hedging: /\b(generally|typically|often|various|numerous)\b/gi,
  aiCloser: /(hope this helps|let me know if you need|feel free to)/gi,
};
function scan(text) {
  const out = { score: 0, hits: {} };
  for (const [k, re] of Object.entries(TELLS)) {
    const m = text.match(re) || [];
    out.hits[k] = m.length;
    out.score += m.length * (k === "emDash" || k === "bannedWords" ? 3 : 1);
  }
  const sentences = text.split(/[.!?]+/).filter((s) => s.trim().length);
  const lens = sentences.map((s) => s.split(/\s+/).length);
  const avg = lens.reduce((a, b) => a + b, 0) / Math.max(1, lens.length);
  const variance = lens.reduce((a, b) => a + (b - avg) ** 2, 0) / Math.max(1, lens.length);
  out.hits.sentences = sentences.length;
  out.hits.avgLen = Math.round(avg * 10) / 10;
  out.hits.var = Math.round(variance * 10) / 10;
  if (variance < 8 && sentences.length > 3) { out.score += 3; out.hits.uniform = true; }
  out.verdict = out.score === 0 ? "HUMAN" : out.score <= 3 ? "MOSTLY HUMAN" : out.score <= 8 ? "SUSPECT" : "AI";
  return out;
}
// Lead config: {team, chain, contracts:[..], praise:[..](holds), hookPara, checkPara, fee, turnaround, target, deliverable, signer, role}
// Hook file: must contain a line starting "## Hook" whose following non-empty lines form hookPara,
// and a line starting "## Check" forming checkPara. Worker refuses if either is missing.
function section(md, name) {
  const lines = md.split("\n");
  let on = false, buf = [];
  for (const ln of lines) {
    if (ln.trim().toLowerCase() === "## " + name) { on = true; continue; }
    if (on && ln.startsWith("## ")) break;
    if (on) buf.push(ln);
  }
  return buf.join("\n").trim();
}
const [hookPath, leadPath, outPath] = process.argv.slice(2);
if (!hookPath || !leadPath) { console.error("usage: node worker-draft-assembler.mjs <hook.md> <lead.json> [out.md]"); process.exit(2); }
const hook = readFileSync(hookPath, "utf8");
const lead = JSON.parse(readFileSync(leadPath, "utf8"));
const hookPara = section(hook, "hook") || lead.hookPara;
const checkPara = section(hook, "check") || lead.checkPara;
if (!hookPara || !checkPara) { console.error("refused: hook needs ## Hook/## Check sections or lead.hookPara/lead.checkPara"); process.exit(3); }
const subject = lead.subject;
const body = `Hi ${lead.team} team,

${lead.praise} That is ${lead.praiseAdj || "clean work"}.

${hookPara} ${checkPara}

Why trust my filter: I trace vault accounting full time with a kill-or-confirm rule. Current ledger is 14 complex vectors traced and closed across Euler plus Morpho and Pendle V2 with line cites, plus a filed Cantina submission with a green Forge PoC. If I flag a path, it ships with a runnable repro. If code holds, I say so.

Scope and terms:
- Fixed fee: ${lead.fee}
- Turnaround: ${lead.turnaround}
- Target: ${lead.target}
- Deliverable: ${lead.deliverable}

If you want a second set of eyes on this surface before deposits scale, reply here and I'll start there.

Best,
${lead.signer}
${lead.role}`;
const follow = `Bumping once with the DIY cut: ${lead.followCut} Happy to run the full ${lead.turnaround} pass (${lead.fee}) if useful, or leave you with the check.`;
const r1 = scan(subject + "\n" + body), r2 = scan(follow);
const doc = `# ${lead.team} outreach (WORKER-STAGED, HOLD, not sent)
## Gates: contact ${lead.contactStatus || "UNVERIFIED"}; currency ${lead.fee}; hook ${hookPath}.
## Tell-scan: draft ${r1.verdict} (score ${r1.score}), follow-up ${r2.verdict} (score ${r2.score}).
## Email
Subject: ${subject}

${body}

## Follow-up
Subject: Re: ${lead.followSubject || subject}

${follow}

## Status
WORKER-STAGED AND HOLD. Human review + explicit send command required. Nothing sent.
`;
if (outPath) writeFileSync(outPath, doc);
console.log(JSON.stringify({ draft: r1.verdict, draftScore: r1.score, follow: r2.verdict, followScore: r2.score, out: outPath || null }));

// Scene list for the BidFusion product demo.
//
// Single source of truth for the recording (record_demo.mjs), the voice-over
// (synthesize_voiceover.mjs) and the narration script it emits. Every scene:
//   id        stable key, also used for the voice clip file name
//   act       'live' | 'preview' | 'status'  (drives the lower-third label)
//   title     lower-third text shown during the scene
//   status    what the page really is, so the speaker never over-claims
//   minDwell  seconds the scene is held at minimum; grows to fit the voice clip
//   narration English voice-over text (~140 wpm)
//   steps     actions executed at the start of the scene (see record_demo.mjs)
//
// Locator specs used in steps:
//   { role, name }   getByRole  (name may be a RegExp)
//   { label }        getByLabel
//   { summary }      a <details> <summary> containing the text
//   { text }         getByText
//   { css, nth }     CSS selector, optional index
// Step kinds: goto, click, fill, select, scroll, scrollTo, pause, hover, title.

export const ACT_LABELS = {
  live: 'LIVE · synthetic package',
  preview: 'PREVIEW · curated demonstration data',
  status: 'PRODUCT STATUS · measured',
};

export const scenes = [
  {
    id: '01-overview',
    act: 'live',
    title: 'The operating system for a bid',
    status: 'LIVE',
    url: '/overview',
    minDwell: 15,
    narration:
      'This is BidFusion, the operating system for a bid you can defend. ' +
      'What you see is the current working prototype and the workflow we are building toward. ' +
      'One workspace spans the seven decision stages of the APMP lifecycle, ' +
      'and every module tells you honestly whether it is live, a preview, or still planned.',
    steps: [
      { goto: '/overview' },
      { pause: 2.5 },
      { scroll: 520 },
      { pause: 2.5 },
      { scroll: 620 },
      { pause: 2 },
      { scroll: 500 },
    ],
  },
  {
    id: '02-intake',
    act: 'live',
    title: 'Bid intake and security gate',
    status: 'LIVE',
    url: '/',
    minDwell: 13,
    narration:
      'A bid begins with intake. Documents can be uploaded into quarantine, ' +
      'or a verified synthetic package is selected. ' +
      'Nothing is parsed or analysed before the security gate has cleared the package. ' +
      'We start with the minimal RFP package and run the security checks.',
    steps: [
      { goto: '/' },
      { pause: 2 },
      { scrollTo: { role: 'heading', name: 'Start with a verified synthetic package' } },
      { pause: 1.5 },
      { click: { css: 'input[name="package"][value="rfp-minimal"]' } },
      { pause: 1.5 },
      { click: { role: 'button', name: 'Run security checks' } },
      { pause: 1 },
    ],
  },
  {
    id: '03-command-center',
    act: 'live',
    title: 'Bid command center',
    status: 'LIVE',
    url: '/runs/<run>',
    minDwell: 16,
    narration:
      'Every run lands in the bid command center: one recorded outcome, one next best action, ' +
      'and the evidence behind every signal. ' +
      'The security gate has cleared all documents of the package, ' +
      'so the full analysis is offered as the next step.',
    steps: [
      { pause: 2.5 },
      { scrollTo: { summary: 'Security gate and document verdicts' } },
      { click: { summary: 'Security gate and document verdicts' } },
      { pause: 3 },
      { scrollTo: { role: 'button', name: 'Run full analysis' } },
      { pause: 1 },
      { click: { role: 'button', name: 'Run full analysis' } },
      { pause: 1 },
    ],
  },
  {
    id: '04-full-run',
    act: 'live',
    title: 'Explainable bid health',
    status: 'LIVE',
    url: '/runs/<run>',
    minDwell: 13,
    narration:
      'The full run extracted the requirements and computed explainable bid health. ' +
      'Coverage here is candidate coverage, not a compliance decision, ' +
      'and the attention list points the bid manager to what needs a person next.',
    steps: [
      { pause: 2 },
      { scrollTo: { role: 'heading', name: 'Where this bid stands' } },
      { pause: 2 },
      { click: { summary: 'Show counted bid facts' } },
      { pause: 2 },
    ],
  },
  {
    id: '05-workbench',
    act: 'live',
    title: 'Requirement workbench and human review',
    status: 'LIVE',
    url: '/runs/<run>/knowledge-assessment',
    minDwell: 26,
    narration:
      'The requirement workbench is where a sentence from the RFP becomes work. ' +
      'Each requirement keeps its source, its machine candidate match, ' +
      'and evidence from golden knowledge. ' +
      'The human decision is recorded separately, versioned, and applies to this bid only. ' +
      'Machine evidence supports the review. It never replaces it.',
    steps: [
      { click: { css: '.bid-context-nav a[href$="/knowledge-assessment"]' } },
      { pause: 2.5 },
      { click: { role: 'link', name: /^Mandatory/ } },
      { pause: 2 },
      { scrollTo: { role: 'heading', name: 'Analysis & evidence' } },
      { pause: 3 },
      { scrollTo: { role: 'heading', name: 'Human decision' } },
      { select: { css: 'select[name="decision"]' }, value: 'CONFIRMED' },
      { pause: 0.8 },
      { fill: { css: 'input[name="reviewer"]' }, value: 'Demo Reviewer' },
      { pause: 0.8 },
      { fill: { css: 'textarea[name="rationale"]' }, value: 'Evidence matches the MTD service description.' },
      { pause: 1 },
      { click: { role: 'button', name: 'Record decision' } },
      { pause: 1.5 },
      { scrollTo: { role: 'heading', name: 'Human decision' } },
    ],
  },
  {
    id: '06-working-package',
    act: 'live',
    title: 'Working package and reviewed projection',
    status: 'LIVE',
    url: '/runs/<run>/working-package',
    minDwell: 18,
    narration:
      'The working package is the hand-over: executive overview, deadlines, requirements and open questions, ' +
      'available as a structured view, as JSON, or as Markdown. ' +
      'Generating the reviewed working package projects the recorded human decisions onto it, ' +
      'with provenance for every statement.',
    steps: [
      { click: { css: '.bid-context-nav a[href$="/working-package"]' } },
      { pause: 2 },
      { click: { css: '.view-toggle a[href$="view=json"]' } },
      { pause: 2 },
      { click: { css: '.view-toggle a[href$="view=md"]' } },
      { pause: 2 },
      { click: { css: '.view-toggle a[href$="view=structured"]' } },
      { pause: 1.5 },
      { scrollTo: { role: 'button', name: 'Generate Reviewed Working Package' } },
      { click: { role: 'button', name: 'Generate Reviewed Working Package' } },
      { pause: 2 },
    ],
  },
  {
    id: '07-golden-knowledge',
    act: 'live',
    title: 'Golden knowledge: MTD pilot corpus',
    status: 'LIVE (internal pilot data)',
    url: '/golden-knowledge',
    minDwell: 13,
    narration:
      'Golden knowledge is what BidFusion currently knows about Managed Threat Detection. ' +
      'The pilot corpus is inventoried by technology and document family, ' +
      'and every extracted claim keeps its source file, section and version.',
    steps: [
      { goto: '/golden-knowledge' },
      { pause: 2.5 },
      { scrollTo: { role: 'heading', name: 'Knowledge by technology and document family' } },
      { pause: 2.5 },
      { scrollTo: { role: 'heading', name: 'Inventoried sources' } },
      { click: { summary: 'File inventory' } },
      { pause: 1 },
      { scroll: 300 },
    ],
  },
  {
    id: '08-matching',
    act: 'live',
    title: 'Capability matching',
    status: 'LIVE',
    url: '/golden-knowledge/matching',
    minDwell: 11,
    narration:
      'Capability matching connects requirements to those claims deterministically. ' +
      'Every hit is explainable, and every claim stays marked as unverified until a person confirms it.',
    steps: [
      { click: { css: '.module-nav a[href$="/golden-knowledge/matching"]' } },
      { pause: 2 },
      { scroll: 500 },
      { pause: 2 },
      { scroll: 500 },
    ],
  },
  {
    id: '09-qualification',
    act: 'preview',
    title: 'Qualification (preview)',
    status: 'PREVIEW',
    url: '/qualification',
    minDwell: 13,
    narration:
      'From here on, the modules are previews on curated demonstration data, and each page says so. ' +
      'Qualification comes first: must-pass factors, conditions and evidence gaps ' +
      'lead to a bid or no-bid decision that stays with people.',
    steps: [
      { goto: '/qualification' },
      { pause: 2 },
      { scrollTo: { role: 'heading', name: 'Must-pass factors' } },
      { pause: 2.5 },
      { scrollTo: { role: 'heading', name: 'The decision itself' } },
      { pause: 2 },
      { scrollTo: { summary: "Where this module's data comes from" } },
      { click: { summary: "Where this module's data comes from" } },
    ],
  },
  {
    id: '10-compliance',
    act: 'preview',
    title: 'Compliance matrix (preview)',
    status: 'PREVIEW',
    url: '/compliance',
    minDwell: 13,
    narration:
      'The compliance preview connects requirements with status, gaps and questions for the customer. ' +
      'Switching to the high-risk scenario shows how missing information becomes visible ' +
      'before it turns into a bid failure.',
    steps: [
      { goto: '/compliance' },
      { pause: 2 },
      { scroll: 450 },
      { pause: 1.5 },
      { scrollTo: { summary: 'Demonstration scenario' } },
      { click: { summary: 'Demonstration scenario' } },
      { pause: 1 },
      { click: { role: 'link', name: 'High-risk opportunity' } },
      { pause: 1.5 },
      { scrollTo: { role: 'heading', name: 'Where compliance stands' } },
    ],
  },
  {
    id: '11-strategy',
    act: 'preview',
    title: 'Competitors and win strategy (preview)',
    status: 'PREVIEW',
    url: '/competitive-intelligence',
    minDwell: 13,
    narration:
      'Portfolio and strategy: competitor focus, signals and a battle card, ' +
      'and the win strategy with customer hot buttons and win themes. ' +
      'Every statement carries a label that says where it would come from.',
    steps: [
      { goto: '/competitive-intelligence' },
      { pause: 1.5 },
      { scrollTo: { role: 'heading', name: 'The field' } },
      { click: { css: 'main a[href*="focus="]', nth: 1 } },
      { pause: 2 },
      { scroll: 400 },
      { pause: 1.5 },
      { click: { css: '.module-nav a[href$="/win-strategy"]' } },
      { pause: 1.5 },
      { scrollTo: { role: 'heading', name: 'Win themes' } },
    ],
  },
  {
    id: '12-extraction-quality',
    act: 'status',
    title: 'Extraction quality: measured against real RFPs',
    status: 'MEASURED',
    url: '/extraction-quality',
    minDwell: 15,
    narration:
      'Product status is measured, not claimed. ' +
      'Requirement extraction is evaluated against a frozen ground truth from real RFPs. ' +
      'The trend shows the path from zero detections to Milestone A, ' +
      'the gaps that remain, and what pilot readiness still needs.',
    steps: [
      { goto: '/extraction-quality' },
      { pause: 2.5 },
      { scrollTo: { role: 'heading', name: 'From zero real detections to Milestone A' } },
      { pause: 3 },
      { scrollTo: { role: 'heading', name: 'Coverage by RFP Document' } },
      { pause: 2 },
      { scrollTo: { role: 'heading', name: 'Remaining Extraction Gaps' } },
    ],
  },
  {
    id: '13-roadmap',
    act: 'status',
    title: 'Architecture and roadmap',
    status: 'LIVE (product record)',
    url: '/architecture-roadmap',
    minDwell: 11,
    narration:
      'The architecture and roadmap page shows what is built, what is next, ' +
      'and what each step depends on, with a status and data mode for every feature.',
    steps: [
      { goto: '/architecture-roadmap' },
      { pause: 2 },
      { scrollTo: { role: 'heading', name: 'Delivery phases' } },
      { pause: 2 },
      { scrollTo: { role: 'heading', name: 'Every feature at a glance' } },
      { pause: 1 },
      { scroll: 300 },
    ],
  },
  {
    id: '14-close',
    act: 'live',
    title: 'One RFP. One source of truth. One bid workspace.',
    status: 'LIVE',
    url: '/overview',
    minDwell: 8,
    narration:
      'One RFP. One source of truth. One bid workspace. ' +
      'This is BidFusion today, and the direction we are building toward.',
    steps: [
      { goto: '/overview' },
      { pause: 1.5 },
      { click: { summary: 'Jump to anything' } },
      { pause: 1 },
    ],
  },
];

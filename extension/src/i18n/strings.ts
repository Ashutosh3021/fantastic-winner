import type { Language } from "../schemas";

/**
 * UI strings only (§9.4).
 *
 * AI-generated content arrives already in the user's language from the backend;
 * what lives here is the chrome around it. Technical terms stay English in both
 * cases — that is a product rule, not a translation gap.
 */

type Strings = {
  brand: string;
  problemDetected: (title: string) => string;
  approachesHeading: string;
  recommended: string;
  chooseApproach: string;
  creditCost: (cost: number, left: number) => string;
  switchResets: string;
  conceptStillDontGet: string;
  startMicroQuestions: string;
  microQuestionOf: (index: number, total: number) => string;
  yourAnswer: string;
  checkUnderstanding: string;
  needHint: (used: number, total: number) => string;
  showMeThisStep: string;
  nextQuestion: string;
  allDoneHeading: string;
  writeItNow: string;
  checklistCollapsed: string;
  revealPlan: string;
  openAnalysis: string;
  creditsUsed: (used: number, limit: number) => string;
  resetsAt: (time: string) => string;
  creditsExhaustedBody: string;
  offlineBody: string;
  manualPasteBody: string;
  pastePlaceholder: string;
  retry: string;
  signInRequired: string;
  openSettings: string;
  networkErrorBody: string;
  busyBody: string;
};

const en: Strings = {
  brand: "CodeMentor",
  problemDetected: (title) => `Problem detected: ${title}`,
  approachesHeading: "Possible ways to think:",
  recommended: "Recommended",
  chooseApproach: "Choose how you want to learn this problem.",
  creditCost: (cost, left) => `The questions use ${cost} of your ${left} question credits.`,
  switchResets: "Switching resets your progress on this problem.",
  conceptStillDontGet: "I still don't get it",
  startMicroQuestions: "Start micro-questions",
  microQuestionOf: (index, total) => `Micro-question ${index} / ${total}`,
  yourAnswer: "Your answer",
  checkUnderstanding: "Check understanding",
  needHint: (used, total) => `Need a hint · ${used} of ${total}`,
  showMeThisStep: "Show me this step",
  nextQuestion: "Next question",
  allDoneHeading: "You've completed all micro-questions.",
  writeItNow: "Now write the full solution in the LeetCode editor.",
  checklistCollapsed: "Checklist",
  revealPlan: "Reveal the plan",
  openAnalysis: "Open Solution Analysis",
  creditsUsed: (used, limit) => `Question credits: ${used} / ${limit}`,
  resetsAt: (time) => `Resets at ${time}`,
  creditsExhaustedBody:
    "Your saved concepts, mistake journal, and previous sessions are still available.",
  offlineBody:
    "CodeMentor needs a connection to check your answers. Your place in this problem is saved — nothing you have done is lost.",
  manualPasteBody: "Couldn't read this page. Paste the problem statement.",
  pastePlaceholder: "Paste the problem statement here…",
  retry: "Try again",
  signInRequired: "Sign in to start learning this problem.",
  openSettings: "Open settings",
  networkErrorBody: "CodeMentor needs a connection to check your answers.",
  busyBody: "The mentor is busy. Retrying shortly…",
};

const hi: Strings = {
  ...en,
  brand: "CodeMentor",
  problemDetected: (title) => `Problem detected: ${title}`,
  approachesHeading: "Sochne ke tarike:",
  recommended: "Recommended",
  chooseApproach: "Choose how you want to learn this problem.",
  creditCost: (cost, left) => `Sawal aapke ${left} question credits mein se ${cost} use karega.`,
  switchResets: "Switching resets your progress on this problem.",
  conceptStillDontGet: "I still don't get it",
  startMicroQuestions: "Start micro-questions",
  microQuestionOf: (index, total) => `Micro-question ${index} / ${total}`,
  yourAnswer: "Aapka answer",
  checkUnderstanding: "Check understanding",
  needHint: (used, total) => `Hint chahiye · ${total} mein se ${used}`,
  showMeThisStep: "Show me this step",
  nextQuestion: "Next question",
  allDoneHeading: "You've completed all micro-questions.",
  writeItNow: "Ab poori solution LeetCode editor mein likhein.",
  checklistCollapsed: "Checklist",
  revealPlan: "Plan dekhein",
  openAnalysis: "Solution Analysis kholen",
  creditsUsed: (used, limit) => `Question credits: ${used} / ${limit}`,
  resetsAt: (time) => `${time} par reset hoga`,
  creditsExhaustedBody:
    "Aapke saved concepts, mistake journal aur purane sessions abhi bhi available hain.",
  offlineBody:
    "Answer check karne ke liye CodeMentor ko connection chahiye. Aapki jagah save hai — jo kiya hai wo kuch nahi gaya.",
  manualPasteBody: "Ye page padha nahi ja saka. Problem statement paste karein.",
  pastePlaceholder: "Problem statement yahan paste karein…",
  retry: "Dobara try karein",
  signInRequired: "Sign in karein taaki seekhna shuru kar sakein.",
  openSettings: "Settings kholein",
  networkErrorBody: "Answer check karne ke liye CodeMentor ko connection chahiye.",
  busyBody: "Mentor abhi busy hai. Thodi der mein dobara try kar rahe hain…",
};

// Odia ships only once its leak corpus passes (§11.4); until then it falls back
// to English chrome, which is the honest behaviour.
const or: Strings = { ...en };

const TABLES: Record<Language, Strings> = { en, hi, or };

export function strings(language: Language): Strings {
  return TABLES[language] ?? TABLES.en;
}
/**
 * The learner-facing state machine (§7.3).
 *
 * One store owns the whole overlay: which stage we are in, the server's truth
 * (session, current question, checklist, credits), and the UI-only bits that
 * survive a page navigation. The client *displays* unlock and credit state but
 * never decides it — every value here arrives from a response.
 */

import { create } from "zustand";

import type {
  ApiError,
  Approach,
  ApproachesResponse,
  ChecklistResponse,
  ConceptCard,
  CurrentQuestion,
  HintResponse,
  Language,
  ProblemData,
  SessionSummary,
  SimplifyResponse,
  Usage,
  AnswerResponse,
  AnalysisResponse,
} from "../schemas";
import { ApiFailure } from "../api/errors";
import { api, newIdempotencyKey } from "./client";
import { flush, track } from "../telemetry";

export type Stage =
  | "idle"
  | "manual"
  | "approaches"
  | "concept"
  | "questioning"
  | "solution"
  | "analyzed";

export type Pending =
  | "none"
  | "extract"
  | "approaches"
  | "session"
  | "concept"
  | "simplify"
  | "questions"
  | "answer"
  | "hint"
  | "checklist"
  | "analysis";

type DraftAnswer = { text: string; choiceIndexes: number[]; order: number[] };

const EMPTY_DRAFT: DraftAnswer = { text: "", choiceIndexes: [], order: [] };

const DEFAULT_USAGE: Usage = {
  question_credits_used: 0,
  question_credits_limit: 12,
  window_start: new Date(0).toISOString(),
  window_end: new Date(0).toISOString(),
  active_sessions: 0,
  max_active_sessions: 3,
  min_plan_credits: 3,
};

type LearnerState = {
  stage: Stage;
  pending: Pending;

  problem: ProblemData | null;
  extractionNote: string | null;

  approaches: Approach[];
  recommendedFirst: string | null;
  problemType: string | null;

  session: SessionSummary | null;
  concept: ConceptCard | null;
  simplifiedLevel: number;
  simplifiedText: string | null;
  simplifiedWhy: string | null;

  question: CurrentQuestion | null;
  draft: DraftAnswer;
  feedback: AnswerResponse | null;
  hint: HintResponse | null;

  checklist: ChecklistResponse | null;

  analysis: AnalysisResponse | null;
  analysisLanguage: string | null;
  analysisAmbiguous: boolean;
  /** `paste` means the bridge could not read the editor and we asked instead. */
  analysisMode: "idle" | "paste";

  usage: Usage | null;
  language: Language;
  error: ApiError | null;
  notice: string | null;

  setProblem: (problem: ProblemData | null, note?: string | null) => void;
  setPending: (pending: Pending) => void;
  setNotice: (notice: string | null) => void;
  setError: (error: ApiError | null) => void;
  setUsage: (usage: Partial<Usage> | null) => void;
  setLanguage: (language: Language) => void;
  setDraft: (draft: Partial<DraftAnswer>) => void;

  loadApproaches: () => Promise<void>;
  chooseApproach: (approachId: string) => Promise<void>;
  switchApproach: (approachId: string) => Promise<void>;
  loadConcept: (simplify?: boolean) => Promise<void>;
  startQuestions: () => Promise<void>;
  submitAnswer: () => Promise<void>;
  requestHint: () => Promise<void>;
  revealStep: () => Promise<void>;
  loadChecklist: () => Promise<void>;
  loadAnalysis: (code: string, editorLanguage: string, ambiguous: boolean) => Promise<void>;
  completeSession: () => Promise<void>;
  reset: () => void;
};

function toApiError(cause: unknown): ApiError {
  if (cause instanceof ApiFailure) return cause.toApiError();
  return { code: "unknown", message: cause instanceof Error ? cause.message : "Something went wrong." };
}

function applyUsageMeta(creditsRemaining?: number, creditsResetAt?: string): void {
  if (creditsRemaining === undefined) return;
  useLearnerStore.setState((state) => {
    if (!state.usage) return state;
    const used = Math.max(0, state.usage.question_credits_limit - creditsRemaining);
    return {
      usage: {
        ...state.usage,
        question_credits_used: used,
        ...(creditsResetAt ? { window_end: creditsResetAt } : {}),
      },
    };
  });
}

export const useLearnerStore = create<LearnerState>((set, get) => ({
  stage: "idle",
  pending: "none",

  problem: null,
  extractionNote: null,

  approaches: [],
  recommendedFirst: null,
  problemType: null,

  session: null,
  concept: null,
  simplifiedLevel: 0,
  simplifiedText: null,
  simplifiedWhy: null,

  question: null,
  draft: EMPTY_DRAFT,
  feedback: null,
  hint: null,

  checklist: null,

  analysis: null,
  analysisLanguage: null,
  analysisAmbiguous: false,
  analysisMode: "idle",

  usage: null,
  language: "en",
  error: null,
  notice: null,

  setProblem: (problem, note = null) => set({ problem, extractionNote: note }),
  setPending: (pending) => set({ pending }),
  setNotice: (notice) => set({ notice }),
  setError: (error) => set({ error }),
  setUsage: (usage) =>
    set((state) => ({
      // `/me` returns a smaller snapshot than `/usage`; merge so a partial read
      // never blanks out fields we already know.
      usage: usage ? { ...DEFAULT_USAGE, ...state.usage, ...usage } : null,
    })),
  setDraft: (draft) => set((state) => ({ draft: { ...state.draft, ...draft } })),
  setLanguage: (language) => set({ language }),

  reset: () =>
    set({
      stage: "idle",
      pending: "none",
      approaches: [],
      recommendedFirst: null,
      problemType: null,
      session: null,
      concept: null,
      simplifiedLevel: 0,
      simplifiedText: null,
      simplifiedWhy: null,
      question: null,
      draft: EMPTY_DRAFT,
      feedback: null,
      hint: null,
      checklist: null,
      analysis: null,
      analysisLanguage: null,
      analysisAmbiguous: false,
  analysisMode: "idle",
      error: null,
      notice: null,
    }),

  loadApproaches: async () => {
    const problem = get().problem;
    if (!problem) return;
    set({ pending: "approaches", error: null });
    try {
      const res = await api("approaches", { body: { problem } });
      const data = res.data as ApproachesResponse;
      set({
        approaches: data.approaches,
        recommendedFirst: data.recommended_first,
        problemType: data.problem_type,
        stage: get().stage === "idle" ? "approaches" : get().stage,
      });
      track("approaches_shown", { slug: problem.slug, count: data.approaches.length });
    } catch (cause) {
      set({ error: toApiError(cause) });
    } finally {
      set({ pending: "none" });
    }
  },

  chooseApproach: async (approachId) => {
    const { problem } = get();
    if (!problem) return;
    set({ pending: "session", error: null });
    try {
      const res = await api("sessionsCreate", {
        body: { slug: problem.slug, approach_id: approachId as never, problem },
      });
      set({ session: res.data, stage: "concept" });
      applyUsageMeta(res.meta.creditsRemaining, res.meta.creditsResetAt);
      track("approach_selected", { slug: problem.slug, approach_id: approachId });
      await get().loadConcept();
    } catch (cause) {
      set({ error: toApiError(cause) });
    } finally {
      set({ pending: "none" });
    }
  },

  switchApproach: async (approachId) => {
    const { session, problem } = get();
    if (!session || !problem) return;
    set({ pending: "session", error: null });
    try {
      // The quote comes back before anything commits, so the UI can confirm the
      // cost first (§7.4).
      const quote = await api("sessionPatch", {
        body: { approach_id: approachId as never },
        params: { id: session.id },
      });
      set({
        session: quote.data,
        question: null,
        feedback: null,
        hint: null,
        checklist: null,
        concept: null,
        simplifiedLevel: 0,
        simplifiedText: null,
        simplifiedWhy: null,
        stage: "concept",
      });
      await get().loadConcept();
    } catch (cause) {
      set({ error: toApiError(cause) });
    } finally {
      set({ pending: "none" });
    }
  },

  loadConcept: async (simplify = false) => {
    const session = get().session;
    if (!session) return;
    set({ pending: simplify ? "simplify" : "concept", error: null });
    try {
      if (simplify) {
        const res = await api("conceptSimplify", { params: { id: session.id } });
        const body = res.data as SimplifyResponse;
        set({
          simplifiedLevel: body.simplified.level,
          simplifiedText: body.simplified.simple_explanation,
          simplifiedWhy: body.simplified.why_it_fits_this_problem,
          notice: body.simplified.at_max_level
            ? "That's as simple as it gets. Try the first micro-question — it is designed to be answerable."
            : null,
        });
        track("simplify_clicked", { session_id: session.id, level: body.simplified.level });
        return;
      }

      const res = await api("concept", { params: { id: session.id } });
      set({ concept: (res.data as { card: ConceptCard }).card, simplifiedLevel: 0 });
      track("concept_viewed", { session_id: session.id });
    } catch (cause) {
      set({ error: toApiError(cause) });
    } finally {
      set({ pending: "none" });
    }
  },

  startQuestions: async () => {
    const session = get().session;
    if (!session) return;
    set({ pending: "questions", error: null });
    try {
      const res = await api("microQuestions", {
        params: { id: session.id },
        idempotencyKey: newIdempotencyKey(),
      });
      set({
        question: res.data.question,
        stage: "questioning",
        feedback: null,
        hint: null,
        draft: EMPTY_DRAFT,
      });
      applyUsageMeta(res.meta.creditsRemaining, res.meta.creditsResetAt);
      track("mq_generated", {
        session_id: session.id,
        charged: res.data.credits_charged,
        total: res.data.question.total,
      });
    } catch (cause) {
      set({ error: toApiError(cause) });
    } finally {
      set({ pending: "none" });
    }
  },

  submitAnswer: async () => {
    const { session, question, draft } = get();
    if (!session || !question) return;
    set({ pending: "answer", error: null, hint: null });
    try {
      const startedAt = Date.now();
      const res = await api("microQuestionAnswer", {
        params: { id: session.id, k: String(question.index) },
        body: {
          answer: draft.text,
          ...(draft.choiceIndexes.length > 0 ? { choice_indexes: draft.choiceIndexes } : {}),
          ...(draft.order.length > 0 ? { order: draft.order } : {}),
          hints_used: question.hints_used,
          time_taken_seconds: Math.round((Date.now() - startedAt) / 1000),
        },
      });
      const body = res.data;
      set({
        feedback: body,
        question: body.all_passed ? null : (body.next_question ?? get().question),
        stage: body.all_passed ? "solution" : get().stage,
        draft: EMPTY_DRAFT,
      });
      track("mq_answered", {
        session_id: session.id,
        index: question.index,
        verdict: body.verdict,
      });
      if (body.verdict !== "correct") {
        track("hint_used", { session_id: session.id, index: question.index, level: 0 });
      }
    } catch (cause) {
      set({ error: toApiError(cause) });
    } finally {
      set({ pending: "none" });
    }
  },

  requestHint: async () => {
    const { session, question } = get();
    if (!session || !question) return;
    set({ pending: "hint", error: null });
    try {
      const res = await api("microQuestionHint", {
        params: { id: session.id, k: String(question.index) },
      });
      set({ hint: res.data });
      set((state) =>
        state.question
          ? { question: { ...state.question, hints_used: res.data.level } }
          : state,
      );
      track("hint_used", { session_id: session.id, index: question.index, level: res.data.level });
    } catch (cause) {
      set({ error: toApiError(cause) });
    } finally {
      set({ pending: "none" });
    }
  },

  revealStep: async () => {
    const { session, question } = get();
    if (!session || !question) return;
    set({ pending: "hint", error: null });
    try {
      // §10.8: the dead-end escape hatch. There is no separate "reveal" endpoint
      // in the API (§20), so this goes through the answer route with
      // `hints_used` pinned at the maximum — the server decides whether the
      // attempt cap has been hit and returns the step explanation either way.
      const res = await api("microQuestionAnswer", {
        params: { id: session.id, k: String(question.index) },
        body: { answer: get().draft.text, hints_used: 3, time_taken_seconds: 0 },
      });
      const body = res.data;
      set({
        feedback: body,
        question: {
          ...(body.next_question ?? get().question!),
          revealed: true,
          step_explanation:
            body.next_question?.step_explanation ??
            get().question?.step_explanation ??
            null,
        },
        stage: body.all_passed ? "solution" : get().stage,
        draft: EMPTY_DRAFT,
      });
      track("question_revealed", { session_id: session.id, index: question.index });
    } catch (cause) {
      set({ error: toApiError(cause) });
    } finally {
      set({ pending: "none" });
    }
  },

  loadChecklist: async () => {
    const session = get().session;
    if (!session) return;
    set({ pending: "checklist", error: null });
    try {
      const res = await api("checklist", { params: { id: session.id } });
      set({ checklist: res.data.checklist, stage: "solution" });
      track("checklist_revealed", { session_id: session.id });
    } catch (cause) {
      const error = toApiError(cause);
      // `checklist_locked` is not an error state: the user simply has not earned
      // it yet, and the completion card already explains that.
      if (error.code === "checklist_locked") set({ checklist: null, stage: "solution" });
      else set({ error });
    } finally {
      set({ pending: "none" });
    }
  },

  loadAnalysis: async (code, editorLanguage, ambiguous) => {
    const session = get().session;
    if (!session) return;
    set({ pending: "analysis", error: null, analysisAmbiguous: ambiguous });
    try {
      const res = await api("analysis", {
        params: { id: session.id },
        body: { code, editor_language: editorLanguage },
        idempotencyKey: newIdempotencyKey(),
      });
      set({
        analysis: res.data,
        analysisLanguage: res.data.editor_language,
        stage: "analyzed",
      });
      track("analysis_opened", { session_id: session.id });
    } catch (cause) {
      set({ error: toApiError(cause) });
    } finally {
      set({ pending: "none" });
      void flush();
    }
  },

  completeSession: async () => {
    const session = get().session;
    if (!session) return;
    try {
      const res = await api("sessionPatch", {
        params: { id: session.id },
        body: { status: "completed" },
      });
      set({ session: res.data });
      track("session_completed", { session_id: session.id, approach_id: session.selected_approach });
    } catch (cause) {
      set({ error: toApiError(cause) });
    }
  },
}));
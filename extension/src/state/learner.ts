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
  questionStartedAt: number;
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

  refreshUsage: () => Promise<void>;
  resumeSession: () => Promise<boolean>;
  loadApproaches: () => Promise<void>;
  chooseApproach: (approachId: string) => Promise<void>;
  switchApproach: (approachId: string) => Promise<void>;
  loadConcept: (simplify?: boolean) => Promise<boolean>;
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
  questionStartedAt: 0,
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

  refreshUsage: async () => {
    try {
      const res = await api("usage", {});
      set({ usage: res.data });
    } catch {
      // A stale chip is better than replacing the whole overlay with an error.
    }
  },

  resumeSession: async () => {
    const problem = get().problem;
    if (!problem) return false;
    set({ pending: "session", error: null });
    try {
      const list = await api("sessionsList", {});
      const active = list.data.find(
        (row) =>
          row.slug === problem.slug &&
          (row.status === "in_progress" || row.status === "paused"),
      );
      if (!active) return false;

      const state = await api("sessionGet", { params: { id: active.id } });
      const session = state.data.session;
      set({ session });

      if (state.data.checklist_unlocked) {
        set({
          question: state.data.question,
          feedback: null,
          hint: null,
          draft: EMPTY_DRAFT,
          stage: "solution",
        });
        await get().loadChecklist();
        return true;
      }

      if (state.data.question) {
        set({
          question: state.data.question,
          questionStartedAt: Date.now(),
          feedback: null,
          hint: null,
          draft: EMPTY_DRAFT,
          stage: "questioning",
        });
        return true;
      }

      if (session.question_count > 0) {
        const current = await api("microQuestionCurrent", { params: { id: session.id } });
        set({
          question: current.data,
          questionStartedAt: Date.now(),
          feedback: null,
          hint: null,
          draft: EMPTY_DRAFT,
          stage: "questioning",
        });
        return true;
      }

      set({ stage: "concept" });
      const loaded = await get().loadConcept();
      if (!loaded) {
        set({ stage: "approaches" });
        await get().loadApproaches();
        return false;
      }
      void get().loadApproaches();
      return true;
    } catch (cause) {
      set({ error: toApiError(cause) });
      return false;
    } finally {
      set({ pending: "none" });
    }
  },

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
      questionStartedAt: 0,
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
      set({ session: res.data });
      applyUsageMeta(res.meta.creditsRemaining, res.meta.creditsResetAt);
      track("approach_selected", { slug: problem.slug, approach_id: approachId });
      // Stay on the approach list until the card exists. Entering "concept"
      // first left a blank stage when the concept call failed.
      const loaded = await get().loadConcept();
      set({ stage: loaded ? "concept" : "approaches" });
    } catch (cause) {
      set({ error: toApiError(cause) });
    } finally {
      set({ pending: "none" });
    }
  },

  switchApproach: async (approachId) => {
    const { session, problem, concept } = get();
    if (!session || !problem) return;
    if (approachId === session.selected_approach && concept) return;
    set({ pending: "session", error: null });
    try {
      const res = await api("sessionPatch", {
        body: { approach_id: approachId as never },
        params: { id: session.id },
      });
      // The backend discards the old plan, attempts and hints. Mirror that
      // locally before fetching the new card, so no stale question can render.
      set({
        session: res.data,
        question: null,
        questionStartedAt: 0,
        feedback: null,
        hint: null,
        checklist: null,
        concept: null,
        simplifiedLevel: 0,
        simplifiedText: null,
        simplifiedWhy: null,
        stage: "approaches",
      });
      const loaded = await get().loadConcept();
      set({ stage: loaded ? "concept" : "approaches" });
      track("approach_selected", {
        slug: problem.slug,
        approach_id: approachId,
        switched: true,
      });
    } catch (cause) {
      set({ error: toApiError(cause) });
    } finally {
      set({ pending: "none" });
    }
  },

  loadConcept: async (simplify = false) => {
    const session = get().session;
    if (!session) return false;
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
        return true;
      }

      const res = await api("concept", { params: { id: session.id } });
      set({ concept: (res.data as { card: ConceptCard }).card, simplifiedLevel: 0 });
      track("concept_viewed", { session_id: session.id });
      return true;
    } catch (cause) {
      set({ error: toApiError(cause) });
      return false;
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
        questionStartedAt: Date.now(),
        stage: "questioning",
        feedback: null,
        hint: null,
        draft: EMPTY_DRAFT,
      });
      applyUsageMeta(res.meta.creditsRemaining, res.meta.creditsResetAt);
      void get().refreshUsage();
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
      // Time on task starts when the question is shown, not when Submit is hit.
      const startedAt = get().questionStartedAt || Date.now();
      const res = await api("microQuestionAnswer", {
        params: { id: session.id, k: String(question.index) },
        body: {
          answer: draft.text,
          ...(draft.choiceIndexes.length > 0 ? { choice_indexes: draft.choiceIndexes } : {}),
          ...(draft.order.length > 0 ? { order: draft.order } : {}),
          hints_used: question.hints_used,
          time_taken_seconds: Math.max(0, Math.round((Date.now() - startedAt) / 1000)),
        },
      });
      const body = res.data;
      const current = get().question;
      // A wrong answer keeps the same question; record the server's attempt
      // number locally so the "show me this step" threshold can ever be met.
      const next = body.all_passed
        ? null
        : (body.next_question ?? (current ? { ...current, attempts: body.attempt_no } : null));
      set({
        feedback: body,
        question: next,
        questionStartedAt: body.next_question ? Date.now() : get().questionStartedAt,
        stage: body.all_passed ? "solution" : get().stage,
        draft: EMPTY_DRAFT,
      });
      if (body.all_passed) {
        // The learner has earned the plan; fetch it now. Leaving this to a
        // button that no longer renders meant "Reveal the plan" never appeared.
        await get().loadChecklist();
      }
      track("mq_answered", {
        session_id: session.id,
        index: question.index,
        verdict: body.verdict,
      });
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
      // §10.8: an explicit request releases this step. It is not an answer:
      // no attempt is recorded and no credit is spent.
      const res = await api("microQuestionReveal", {
        params: { id: session.id, k: String(question.index) },
      });
      set((state) =>
        state.question
          ? {
              question: {
                ...state.question,
                revealed: res.data.revealed,
                step_explanation: res.data.step_explanation,
              },
            }
          : state,
      );
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
      void get().refreshUsage();
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
      void get().refreshUsage();
      track("session_completed", { session_id: session.id, approach_id: session.selected_approach });
    } catch (cause) {
      set({ error: toApiError(cause) });
    }
  },
}));
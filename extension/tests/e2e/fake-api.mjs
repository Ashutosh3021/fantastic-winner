import { createServer } from "node:http";

const PORT = Number(process.env.E2E_API_PORT ?? 8787);
const NOW = "2026-11-06T00:00:00Z";
const WINDOW_END = "2026-11-06T05:00:00Z";

const APPROACHES = [
  {
    id: "brute_force",
    name: "Brute Force",
    confidence: 0.6,
    simple_reason: "Try every pair so the goal is concrete before optimising.",
    when_to_use: "When you need a correct baseline first.",
    difficulty_for_beginner: "easy",
    expected_complexity: "O(n^2)",
  },
  {
    id: "hash_map",
    name: "Hash Map",
    confidence: 0.92,
    simple_reason: "Remember values you have seen so each lookup is constant time.",
    when_to_use: "When a pair must be found in one pass.",
    difficulty_for_beginner: "medium",
    expected_complexity: "O(n)",
  },
];

const state = {
  session: null,
  approach: null,
  question: null,
  attempts: 0,
  hints: 0,
  completed: false,
  switchCount: 0,
  planGenerated: 0,
  answerCalls: 0,
  hintCalls: 0,
  revealCalls: 0,
  analysisCalls: 0,
  conceptCalls: 0,
  checklistCalls: 0,
  creditsUsed: 0,
};

function resetState() {
  state.session = null;
  state.approach = null;
  state.question = null;
  state.attempts = 0;
  state.hints = 0;
  state.completed = false;
  state.switchCount = 0;
  state.planGenerated = 0;
  state.answerCalls = 0;
  state.hintCalls = 0;
  state.revealCalls = 0;
  state.analysisCalls = 0;
  state.conceptCalls = 0;
  state.checklistCalls = 0;
  state.creditsUsed = 0;
}

function json(res, status, body) {
  const raw = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(raw),
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "authorization, content-type, idempotency-key, x-client-version",
    "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
  });
  res.end(raw);
}

function ok(res, data, meta = {}) {
  json(res, 200, { data, meta: { cached: false, ...meta } });
}

function fail(res, status, code, message) {
  json(res, status, { error: { code, message } });
}

async function bodyOf(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    return {};
  }
}

function summary() {
  if (!state.session) return null;
  return {
    id: "sess-e2e",
    slug: "two-sum",
    problem_url: "https://leetcode.com/problems/two-sum/",
    title: "Two Sum",
    selected_approach: state.approach,
    status: state.completed ? "completed" : "in_progress",
    unlocked_index: state.question ? 1 : 0,
    question_count: state.question ? 1 : 0,
    passed_count: state.completed ? 1 : 0,
    content_version: 1 + state.switchCount,
    mode: "beginner",
    language: "en",
    updated_at: NOW,
  };
}

function usage() {
  return {
    question_credits_used: state.creditsUsed,
    question_credits_limit: 12,
    window_start: NOW,
    window_end: WINDOW_END,
    active_sessions: state.session && !state.completed ? 1 : 0,
    max_active_sessions: 3,
    min_plan_credits: 3,
  };
}

function preferences() {
  return {
    language: "en",
    difficulty_mode: "beginner",
    theme: "system",
    timezone: "UTC",
    prefs_version: 1,
  };
}

function me() {
  return {
    id: "user-e2e",
    email: "e2e@example.com",
    email_verified: true,
    created_at: NOW,
    preferences: preferences(),
    usage: usage(),
  };
}

function progress() {
  return {
    xp: 40,
    level: 2,
    current_streak: 3,
    longest_streak: 5,
    mastery: [],
    weaknesses: [],
    mistake_type_counts: {},
    activity: [],
    due_reviews: 0,
  };
}

function question() {
  return {
    index: 1,
    total: 1,
    prompt: "What should the hash map store while you scan the array?",
    learning_goal: "Connect each value to the index that produced it.",
    answer_type: "short_text",
    choices: null,
    diagram: null,
    hints_used: state.hints,
    attempts: state.attempts,
    hints_available: true,
    step_explanation: null,
    revealed: false,
  };
}

function concept(title, explanation) {
  return {
    approach_id: state.approach,
    title,
    simple_explanation: explanation,
    why_it_fits_this_problem: "Two Sum asks for a pair, so remembering earlier values avoids a nested loop.",
    common_beginner_mistake: "Storing the current value before checking for its complement can reuse the same index.",
    humour_line: null,
    diagram: null,
    simplified_levels_available: 2,
  };
}

function analysis() {
  return {
    session_id: "sess-e2e",
    time_class: "O(n)",
    space_class: "O(n)",
    complexity_explanation: "One pass over the array, with constant-time hash lookups.",
    line_explanations: [
      { label: "seen lookup", quote: "if target - value in seen:", why: "The complement is checked before insertion." },
    ],
    edge_cases: ["Duplicate values", "Negative numbers"],
    improvement_suggestions: ["Return as soon as the pair is found."],
    related_tricks: ["Trade space for time with a hash map."],
    better_approach: null,
    chart: {
      time_class: "O(n)",
      space_class: "O(n)",
      confidence: "high",
      n_max: 100000,
      n_max_source: "constraints",
      brute_force_class: "O(n^2)",
      budget_ops: 10000000,
      estimated: false,
    },
    trace: null,
    editor_language: "python3",
    language_mismatch: false,
    analyzed_at: NOW,
  };
}

function route(method, pathname) {
  if (method === "OPTIONS") return { kind: "options" };
  if (pathname === "/__state") return { kind: "state" };
  if (pathname === "/__reset") return { kind: "reset" };

  if (pathname === "/v1/me" && method === "GET") return { kind: "me" };
  if (pathname === "/v1/me" && method === "DELETE") return { kind: "null" };
  if (pathname === "/v1/usage" && method === "GET") return { kind: "usage" };
  if (pathname === "/v1/progress" && method === "GET") return { kind: "progress" };
  if (pathname === "/v1/preferences" && method === "PUT") return { kind: "preferences" };
  if (pathname === "/v1/events" && method === "POST") return { kind: "events" };
  if (pathname === "/v1/auth/logout" && method === "POST") return { kind: "null" };
  if (pathname === "/v1/auth/refresh" && method === "POST") return { kind: "refresh" };

  if (pathname === "/v1/problems/approaches" && method === "POST") return { kind: "approaches" };

  if (pathname === "/v1/sessions" && method === "GET") return { kind: "sessionsList" };
  if (pathname === "/v1/sessions" && method === "POST") return { kind: "createSession" };
  if (pathname === "/v1/sessions/sess-e2e" && method === "GET") return { kind: "sessionGet" };
  if (pathname === "/v1/sessions/sess-e2e" && method === "PATCH") return { kind: "sessionPatch" };
  if (pathname === "/v1/sessions/sess-e2e/concept" && method === "POST") return { kind: "concept" };
  if (pathname === "/v1/sessions/sess-e2e/concept/simplify" && method === "POST") {
    return { kind: "simplify" };
  }
  if (pathname === "/v1/sessions/sess-e2e/micro-questions" && method === "POST") {
    return { kind: "generateQuestions" };
  }
  if (pathname === "/v1/sessions/sess-e2e/micro-questions/current" && method === "GET") {
    return { kind: "currentQuestion" };
  }
  if (pathname.match(/^\/v1\/sessions\/sess-e2e\/micro-questions\/\d+\/hint$/) && method === "POST") {
    return { kind: "hint" };
  }
  if (pathname.match(/^\/v1\/sessions\/sess-e2e\/micro-questions\/\d+\/reveal$/) && method === "POST") {
    return { kind: "reveal" };
  }
  if (pathname.match(/^\/v1\/sessions\/sess-e2e\/micro-questions\/\d+\/answer$/) && method === "POST") {
    return { kind: "answer" };
  }
  if (pathname === "/v1/sessions/sess-e2e/checklist" && method === "GET") return { kind: "checklist" };
  if (pathname === "/v1/sessions/sess-e2e/analysis" && method === "POST") return { kind: "analysis" };

  return { kind: "notFound" };
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://127.0.0.1");
  const pathname = url.pathname;
  const method = req.method ?? "GET";
  const match = route(method, pathname);
  const body = await bodyOf(req);

  switch (match.kind) {
    case "options":
      return json(res, 204, {});
    case "state":
      return json(res, 200, state);
    case "reset":
      resetState();
      return json(res, 200, { ok: true });
    case "notFound":
      return fail(res, 404, "not_found", `No fake route for ${method} ${pathname}`);
    case "me":
      return ok(res, me());
    case "null":
      return ok(res, null);
    case "usage":
      return ok(res, usage());
    case "progress":
      return ok(res, progress());
    case "preferences":
      return ok(res, { ...preferences(), ...body });
    case "events":
      return ok(res, { accepted: Array.isArray(body.events) ? body.events.length : 0 });
    case "refresh":
      return ok(res, {
        access_token: "e2e-token",
        refresh_token: "e2e-refresh",
        expires_in: 3600,
      });
    case "approaches":
      return ok(res, {
        problem_type: "array_hashing",
        target_complexity_hint: "O(n)",
        approaches: APPROACHES,
        recommended_first: "hash_map",
      });
    case "sessionsList":
      return ok(res, state.session ? [summary()] : []);
    case "createSession": {
      if (state.session) return ok(res, summary());
      state.session = { slug: body.slug ?? "two-sum" };
      state.approach = body.approach_id ?? "brute_force";
      return ok(res, summary());
    }
    case "sessionGet":
      if (!state.session) return fail(res, 404, "not_found", "Session not found");
      return ok(res, {
        session: summary(),
        question: state.question ? question() : null,
        checklist_unlocked: state.completed,
        analysis_unlocked: state.completed,
      });
    case "sessionPatch": {
      if (!state.session) return fail(res, 404, "not_found", "Session not found");
      if (body.approach_id && body.approach_id !== state.approach) {
        state.approach = body.approach_id;
        state.switchCount += 1;
        state.question = null;
        state.attempts = 0;
        state.hints = 0;
        state.completed = false;
      }
      if (body.status === "completed") state.completed = true;
      return ok(res, summary());
    }
    case "concept":
      if (!state.session) return fail(res, 404, "not_found", "Session not found");
      state.conceptCalls += 1;
      return ok(
        res,
        {
          session_id: "sess-e2e",
          card:
            state.approach === "hash_map"
              ? concept("Hash Map Walkthrough", "Store each value and the index where you saw it.")
              : concept("Brute Force Walkthrough", "Compare every pair until the sum matches."),
        },
        { prefs_version: 1 },
      );
    case "simplify":
      return ok(res, {
        session_id: "sess-e2e",
        simplified: {
          level: 1,
          simple_explanation: "Keep a notebook of values you have already seen.",
          why_it_fits_this_problem: "The notebook answers 'have I seen the missing number?' instantly.",
          humour_line: null,
          at_max_level: false,
        },
      });
    case "generateQuestions":
      if (!state.session) return fail(res, 404, "not_found", "Session not found");
      if (!state.question) {
        state.question = { generated: true };
        state.planGenerated += 1;
        state.attempts = 0;
        state.hints = 0;
        state.creditsUsed = Math.min(12, state.creditsUsed + 3);
      }
      return ok(
        res,
        {
          session_id: "sess-e2e",
          question: question(),
          credits_charged: 3,
        },
        {
          credits_remaining: Math.max(0, 12 - state.creditsUsed),
          credits_reset_at: WINDOW_END,
          credit_cost: 3,
        },
      );
    case "currentQuestion":
      if (!state.question) return fail(res, 404, "not_found", "No question");
      return ok(res, question());
    case "hint":
      state.hintCalls += 1;
      state.hints = Math.min(3, state.hints + 1);
      return ok(res, {
        index: 1,
        level: state.hints,
        text:
          state.hints === 1
            ? "Remember which values you have already walked past."
            : "You need the value and its position.",
        is_last: state.hints >= 3,
      });
    case "reveal":
      state.revealCalls += 1;
      return ok(res, {
        session_id: "sess-e2e",
        index: 1,
        step_explanation:
          "Before you store the current value, check whether its complement is already in the map.",
        revealed: true,
      });
    case "answer": {
      state.answerCalls += 1;
      state.attempts += 1;
      const answer = String(body.answer ?? "").toLowerCase();
      const correct = answer.includes("complement") || answer.includes("index");
      if (correct) {
        state.completed = true;
        return ok(res, {
          verdict: "correct",
          feedback: "Exactly - the map remembers the earlier index.",
          matched_key_points: [1],
          mistake_type: null,
          attempt_no: state.attempts,
          next_question: null,
          all_passed: true,
        });
      }
      return ok(res, {
        verdict: "incorrect",
        feedback: "Not quite yet. Think about what you need to look up later.",
        matched_key_points: [],
        mistake_type: "misunderstood_goal",
        attempt_no: state.attempts,
        next_question: question(),
        all_passed: false,
      });
    }
    case "checklist":
      state.checklistCalls += 1;
      if (!state.completed) return fail(res, 409, "checklist_locked", "The checklist is locked.");
      return ok(res, {
        session_id: "sess-e2e",
        checklist: {
          approach_id: state.approach,
          items: [
            "Create an empty map from value to index.",
            "Check for the complement before inserting.",
            "Return the earlier index and the current index.",
          ],
        },
      });
    case "analysis":
      state.analysisCalls += 1;
      return ok(res, analysis(), { credits_remaining: Math.max(0, 12 - state.creditsUsed) });
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`[fake-api] listening on http://127.0.0.1:${PORT}`);
});

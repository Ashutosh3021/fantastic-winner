"""Pydantic models: the single source of truth for the API contract (§4).

These models are exported to JSON Schema under ``contracts/`` and the extension's
Zod schemas are generated from them, so a field cannot drift between the two
sides without CI noticing (ADR-18).

The shapes here mirror ``extension/src/schemas/`` one-for-one. Where the
extension has a discriminated union for diagram specs, the same union appears
below - and ``LearningDiagramSpec`` deliberately has no ``reveals_solution``
field, because ``extra="forbid"`` then makes the capability *unreachable* from
the generation path rather than merely guarded (§12.5).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class Language(StrEnum):
    EN = "en"
    HI = "hi"
    OR = "or"

class DifficultyMode(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"

class Theme(StrEnum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"

class SessionStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"

class AnswerType(StrEnum):
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    ORDER_STEPS = "order_steps"
    FILL_BLANK = "fill_blank"
    PREDICT_STATE = "predict_state"
    SHORT_TEXT = "short_text"

class Verdict(StrEnum):
    CORRECT = "correct"
    PARTIAL = "partial"
    INCORRECT = "incorrect"

class MistakeType(StrEnum):
    OFF_BY_ONE = "off_by_one"
    WRONG_DATA_STRUCTURE = "wrong_data_structure"
    MISSED_EDGE_CASE = "missed_edge_case"
    WRONG_CONDITION = "wrong_condition"
    MISUNDERSTOOD_GOAL = "misunderstood_goal"
    COMPLEXITY_ISSUE = "complexity_issue"
    OTHER = "other"

class ApproachId(StrEnum):
    BRUTE_FORCE = "brute_force"
    HASH_MAP = "hash_map"
    TWO_POINTERS = "two_pointers"
    SLIDING_WINDOW = "sliding_window"
    BINARY_SEARCH = "binary_search"
    PREFIX_SUM = "prefix_sum"
    STACK = "stack"
    MONOTONIC_STACK = "monotonic_stack"
    HEAP = "heap"
    DFS = "dfs"
    BFS = "bfs"
    BACKTRACKING = "backtracking"
    DYNAMIC_PROGRAMMING = "dynamic_programming"
    GREEDY = "greedy"
    SORTING = "sorting"
    UNION_FIND = "union_find"
    TRIE = "trie"
    BIT_MANIPULATION = "bit_manipulation"
    MATH = "math"

class Difficulty(StrEnum):
    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"
    UNKNOWN = "Unknown"

class ComplexityClass(StrEnum):
    O1 = "O(1)"
    OLOGN = "O(log n)"
    ON = "O(n)"
    ONLOGN = "O(n log n)"
    ON2 = "O(n^2)"
    ON3 = "O(n^3)"
    O2N = "O(2^n)"
    OFACT = "O(n!)"

class VerdictConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

# -- problem ---

class ConstraintBound(Base):
    var: str = Field(min_length=1)
    min: float | None = None
    max: float | None = None

class Example(Base):
    input: str
    output: str = ""
    explanation: str = ""

class ProblemData(Base):
    slug: str = Field(pattern=r"^[a-z0-9-]+$", max_length=200)
    url: str = Field(max_length=500)
    title: str = Field(min_length=1, max_length=300)
    difficulty: Difficulty = Difficulty.UNKNOWN
    statement_text: str = Field(default="", max_length=20_000)
    examples: list[Example] = Field(default_factory=list, max_length=10)
    constraints_text: str = Field(default="", max_length=5_000)
    constraint_bounds: list[ConstraintBound] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=20)
    editor_language: str = Field(default="", max_length=40)
    content_hash: str | None = Field(default=None, max_length=120)
    extraction_quality: Literal["full", "partial", "manual"] = "partial"

class ApproachesRequest(Base):
    problem: ProblemData

# -- approaches ---

class Approach(Base):
    id: ApproachId
    name: str
    confidence: float = Field(ge=0.0, le=1.0)
    simple_reason: str
    when_to_use: str
    difficulty_for_beginner: Literal["easy", "medium", "hard"]
    expected_complexity: str | None = None

class ApproachesResponse(Base):
    problem_type: str
    target_complexity_hint: str | None = None
    approaches: list[Approach]
    recommended_first: ApproachId

# -- diagrams ---

DIAGRAM_LIMITS = {
    "max_items": 12,
    "max_frames": 6,
    "max_caption_chars": 120,
    "max_title_chars": 80,
    "max_alt_text_chars": 400,
    "max_json_bytes": 16_000,
}

FrameCaption = Annotated[str, Field(min_length=1, max_length=120)]
Title = Annotated[str, Field(min_length=1, max_length=80)]
AltText = Annotated[str, Field(min_length=1, max_length=400)]
CellValue = Annotated[str, Field(max_length=40)]

class Pointer(Base):
    id: str = Field(min_length=1, max_length=24)
    index: int = Field(ge=0)
    label: str = Field(min_length=1, max_length=24)

class Range(Base):
    from_: int = Field(ge=0, alias="from")
    to: int = Field(ge=0)
    style: Literal["window", "invalid", "active", "result", "plain"] = "plain"

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

class Highlight(Base):
    index: int = Field(ge=0)
    style: Literal["conflict", "active", "visited", "result", "muted"] = "muted"

class Annotation(Base):
    index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=60)

class SidePanel(Base):
    type: Literal["set", "map", "list", "stack", "queue", "text"]
    title: str = Field(min_length=1, max_length=40)
    items: list[str] = Field(default_factory=list, max_length=24)

class Frame(Base):
    caption: FrameCaption
    pointers: list[Pointer] = Field(default_factory=list, max_length=6)
    ranges: list[Range] = Field(default_factory=list, max_length=6)
    highlights: list[Highlight] = Field(default_factory=list, max_length=24)
    annotations: list[Annotation] = Field(default_factory=list, max_length=12)
    side_panel: SidePanel | None = None

class ArrayData(Base):
    cells: list[CellValue] = Field(min_length=1, max_length=12)
    cell_type: Literal["char", "number", "mixed"] = "char"

class GridData(Base):
    rows: list[list[CellValue]] = Field(min_length=1, max_length=12)

class TableData(Base):
    columns: list[CellValue] = Field(min_length=1, max_length=12)
    rows: list[list[CellValue]] = Field(min_length=1, max_length=12)

class SlotsData(Base):
    slots: list[CellValue] = Field(min_length=1, max_length=12)
    orientation: Literal["horizontal", "vertical"] = "vertical"
    label: Title | None = None

class DiagramNode(Base):
    id: str = Field(min_length=1, max_length=24)
    label: str = Field(default="", max_length=40)

class DiagramEdge(Base):
    from_: str = Field(min_length=1, max_length=24, alias="from")
    to: str = Field(min_length=1, max_length=24)
    label: str | None = Field(default=None, max_length=24)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

class NodesData(Base):
    nodes: list[DiagramNode] = Field(min_length=1, max_length=12)
    edges: list[DiagramEdge] = Field(default_factory=list, max_length=24)

class IntervalRow(Base):
    label: str = Field(default="", max_length=24)
    start: float = Field(ge=0)
    end: float = Field(ge=0)

class IntervalsData(Base):
    labels: list[str] = Field(default_factory=list, max_length=12)
    rows: list[IntervalRow] = Field(min_length=1, max_length=6)

class StepsData(Base):
    steps: list[Annotated[str, Field(max_length=60)]] = Field(min_length=1, max_length=12)

class ArrayPointersDiagram(Base):
    kind: Literal["array_pointers"]
    data: ArrayData
    title: Title
    alt_text: AltText
    frames: list[Frame] = Field(min_length=1, max_length=6)

class DpTableDiagram(Base):
    kind: Literal["dp_table"]
    data: TableData
    title: Title
    alt_text: AltText
    frames: list[Frame] = Field(min_length=1, max_length=6)

class GridDiagram(Base):
    kind: Literal["grid"]
    data: GridData
    title: Title
    alt_text: AltText
    frames: list[Frame] = Field(min_length=1, max_length=6)

class HashmapTableDiagram(Base):
    kind: Literal["hashmap_table"]
    data: TableData
    title: Title
    alt_text: AltText
    frames: list[Frame] = Field(min_length=1, max_length=6)

class StackQueueDiagram(Base):
    kind: Literal["stack_queue"]
    data: SlotsData
    title: Title
    alt_text: AltText
    frames: list[Frame] = Field(min_length=1, max_length=6)

class LinkedListDiagram(Base):
    kind: Literal["linked_list"]
    data: NodesData
    title: Title
    alt_text: AltText
    frames: list[Frame] = Field(min_length=1, max_length=6)

class TreeDiagram(Base):
    kind: Literal["tree"]
    data: NodesData
    title: Title
    alt_text: AltText
    frames: list[Frame] = Field(min_length=1, max_length=6)

class RecursionTreeDiagram(Base):
    kind: Literal["recursion_tree"]
    data: NodesData
    title: Title
    alt_text: AltText
    frames: list[Frame] = Field(min_length=1, max_length=6)

class GraphDiagram(Base):
    kind: Literal["graph"]
    data: NodesData
    title: Title
    alt_text: AltText
    frames: list[Frame] = Field(min_length=1, max_length=6)

class IntervalsDiagram(Base):
    kind: Literal["intervals"]
    data: IntervalsData
    title: Title
    alt_text: AltText
    frames: list[Frame] = Field(min_length=1, max_length=6)

class FlowStepsDiagram(Base):
    kind: Literal["flow_steps"]
    data: StepsData
    title: Title
    alt_text: AltText
    frames: list[Frame] = Field(min_length=1, max_length=6)

LearningDiagramSpec = Annotated[
    ArrayPointersDiagram
    | DpTableDiagram
    | GridDiagram
    | HashmapTableDiagram
    | StackQueueDiagram
    | LinkedListDiagram
    | TreeDiagram
    | RecursionTreeDiagram
    | GraphDiagram
    | IntervalsDiagram
    | FlowStepsDiagram,
    Field(discriminator="kind"),
]

class AnalysisTraceSpec(Base):
    """Only constructible on the analysis route (§12.5).

    A trace is allowed to show a full execution, so it carries the capability
    explicitly. A *learning* spec above cannot: ``extra="forbid"`` rejects the
    field outright.
    """

    kind: str
    data: dict[str, Any]
    title: Title
    alt_text: AltText
    frames: list[Frame] = Field(min_length=1, max_length=24)
    reveals_solution: Literal[True]

# -- concept cards ---

class ConceptCard(Base):
    approach_id: str
    title: str = Field(max_length=200)
    simple_explanation: str = Field(max_length=4_000)
    why_it_fits_this_problem: str = Field(max_length=4_000)
    common_beginner_mistake: str = Field(max_length=2_000)
    humour_line: str | None = Field(default=None, max_length=300)
    diagram: LearningDiagramSpec | None = None
    simplified_levels_available: int = Field(default=0, ge=0, le=2)

class SimplifiedConcept(Base):
    level: int = Field(ge=1, le=2)
    simple_explanation: str
    why_it_fits_this_problem: str
    humour_line: str | None = None
    at_max_level: bool = False

class ConceptResponse(Base):
    session_id: str
    card: ConceptCard

class SimplifyResponse(Base):
    session_id: str
    simplified: SimplifiedConcept

# -- sessions ---

class SessionSummary(Base):
    id: str
    slug: str
    problem_url: str
    title: str = ""
    selected_approach: ApproachId
    status: SessionStatus
    unlocked_index: int = Field(ge=0)
    question_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    content_version: int = Field(ge=1)
    mode: DifficultyMode
    language: Language
    updated_at: str

class CreateSessionRequest(Base):
    slug: str = Field(min_length=1, max_length=200)
    approach_id: ApproachId
    problem: ProblemData

class PatchSessionRequest(Base):
    status: Literal["paused", "completed", "abandoned", "in_progress"] | None = None
    approach_id: ApproachId | None = None

class SessionState(Base):
    session: SessionSummary
    question: CurrentQuestion | None = None
    checklist_unlocked: bool = False
    analysis_unlocked: bool = False

class CurrentQuestion(Base):
    """What the client is allowed to see for one question (§10.4).

    ``rubric``, ``common_wrong`` and ``step_explanation`` are not fields here.
    They exist server-side and are never serialised into this model, so "the
    client cannot read ahead" is a property of the type, not of a convention.
    """

    index: int = Field(ge=1)
    total: int = Field(ge=1)
    prompt: str = Field(min_length=1, max_length=1_000)
    learning_goal: str = Field(max_length=1_000)
    answer_type: AnswerType
    choices: list[str] | None = Field(default=None, max_length=8)
    diagram: LearningDiagramSpec | None = None
    hints_used: int = Field(default=0, ge=0)
    attempts: int = Field(default=0, ge=0)
    hints_available: bool = False
    step_explanation: str | None = Field(default=None, max_length=2_000)
    revealed: bool = False

class GenerateQuestionsResponse(Base):
    session_id: str
    question: CurrentQuestion
    credits_charged: int = Field(ge=0)

class HintResponse(Base):
    index: int = Field(ge=1)
    level: int = Field(ge=1, le=3)
    text: str
    is_last: bool

class RevealResponse(Base):
    session_id: str
    index: int = Field(ge=1)
    step_explanation: str
    revealed: bool = True

class AnswerSubmission(Base):
    answer: str = Field(default="", max_length=4_000)
    choice_indexes: list[int] | None = Field(default=None, max_length=12)
    order: list[int] | None = Field(default=None, max_length=12)
    hints_used: int = Field(default=0, ge=0, le=3)
    time_taken_seconds: int = Field(default=0, ge=0, le=86_400)

class AnswerResponse(Base):
    verdict: Verdict
    feedback: str
    matched_key_points: list[int] = Field(default_factory=list)
    mistake_type: MistakeType | None = None
    attempt_no: int = Field(ge=1)
    next_question: CurrentQuestion | None = None
    all_passed: bool = False

class ChecklistItem(Base):
    items: list[Annotated[str, Field(min_length=1, max_length=240)]] = Field(
        min_length=1, max_length=12
    )
    approach_id: str

class ChecklistResponse(Base):
    session_id: str
    checklist: ChecklistItem

# -- preferences and usage ---

class Preferences(Base):
    language: Language = Language.EN
    difficulty_mode: DifficultyMode = DifficultyMode.BEGINNER
    theme: Theme = Theme.SYSTEM
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    prefs_version: int = Field(default=1, ge=1)

class PreferencesPatch(Base):
    language: Language | None = None
    difficulty_mode: DifficultyMode | None = None
    theme: Theme | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)

class Usage(Base):
    question_credits_used: int = Field(ge=0)
    question_credits_limit: int = Field(ge=1)
    window_start: str
    window_end: str
    active_sessions: int = Field(ge=0)
    max_active_sessions: int = Field(ge=1)
    min_plan_credits: int = Field(ge=1)

class MeResponse(Base):
    id: str
    email: EmailStr
    email_verified: bool
    created_at: str
    preferences: Preferences
    usage: dict[str, Any]

# -- progress ---

class ConceptProgressRow(Base):
    concept: ApproachId
    practice_count: int = Field(ge=0)
    mastery: float = Field(ge=0.0, le=1.0)
    last_practiced_at: str | None = None

class Weakness(Base):
    concept: ApproachId
    mistake_type: MistakeType
    weighted_count: float = Field(ge=0)
    distinct_problems: int = Field(ge=1)
    last_seen_at: str

class DailyActivity(Base):
    date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    passed_questions: int = Field(ge=0)

class ProgressResponse(Base):
    xp: int = Field(ge=0)
    level: int = Field(ge=1)
    current_streak: int = Field(ge=0)
    longest_streak: int = Field(ge=0)
    mastery: list[ConceptProgressRow] = Field(default_factory=list)
    weaknesses: list[Weakness] = Field(default_factory=list)
    mistake_type_counts: dict[str, int] = Field(default_factory=dict)
    activity: list[DailyActivity] = Field(default_factory=list, max_length=120)
    due_reviews: int = Field(ge=0)

class MistakeEntry(Base):
    id: str
    concept: ApproachId
    mistake_type: MistakeType
    short_explanation: str
    problem_url: str
    source: Literal["judge", "revealed", "analysis"]
    created_at: str

class MistakeList(Base):
    items: list[MistakeEntry]
    has_more: bool

class ReviewItem(Base):
    id: str
    concept: ApproachId
    review_due_at: str
    priority: Literal["low", "normal", "high"]
    box: int = Field(ge=1)

class ReviewQueueResponse(Base):
    items: list[ReviewItem]

class SavedCard(Base):
    id: str
    slug: str
    title: str
    approach_id: ApproachId
    kind: Literal["concept", "checklist"]
    created_at: str

class SavedCardsResponse(Base):
    items: list[SavedCard]

# -- analysis ---

class AnalysisRequest(Base):
    code: str = Field(min_length=1, max_length=20_000)
    editor_language: str = Field(min_length=1, max_length=40)
    language: str | None = Field(default=None, max_length=40)

class ComplexityChart(Base):
    time_class: ComplexityClass
    space_class: str = Field(min_length=1, max_length=40)
    confidence: VerdictConfidence
    n_max: int = Field(ge=1)
    n_max_source: Literal["constraints", "assumed"]
    brute_force_class: str | None = Field(default=None, max_length=40)
    budget_ops: int = Field(gt=0)
    estimated: bool = False

class CodeExplanation(Base):
    label: str = Field(min_length=1, max_length=80)
    quote: str = Field(default="", max_length=400)
    why: str = Field(min_length=1, max_length=600)

class BetterApproach(Base):
    approach_id: str
    summary: str = Field(max_length=800)
    complexity: str | None = Field(default=None, max_length=40)

class AnalysisResponse(Base):
    session_id: str
    time_class: ComplexityClass
    space_class: str
    complexity_explanation: str
    line_explanations: list[CodeExplanation] = Field(default_factory=list, max_length=12)
    edge_cases: list[str] = Field(default_factory=list, max_length=8)
    improvement_suggestions: list[str] = Field(default_factory=list, max_length=8)
    related_tricks: list[str] = Field(default_factory=list, max_length=6)
    better_approach: BetterApproach | None = None
    chart: ComplexityChart
    trace: AnalysisTraceSpec | None = None
    editor_language: str
    language_mismatch: bool = False
    analyzed_at: str

# -- events ---

class FunnelEvent(Base):
    name: str = Field(max_length=60)
    props: dict[str, Any] = Field(default_factory=dict)

class EventsRequest(Base):
    events: list[FunnelEvent] = Field(min_length=1, max_length=50)

class EventsResponse(Base):
    accepted: int = Field(ge=0)

# -- auth ---

class AuthState(Base):
    signed_in: bool
    email: str | None = None
    emailVerified: bool = False

class CredentialsForm(BaseModel):
    """HTML form post from the hosted login page."""

    model_config = ConfigDict(extra="ignore")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    return_to: str = Field(default="", max_length=500)

class CodeExchangeRequest(Base):
    code: str = Field(min_length=10, max_length=256)

class RefreshRequest(Base):
    refresh_token: str = Field(min_length=10, max_length=512)

class TokenPair(Base):
    access_token: str
    refresh_token: str | None = None
    expires_in: int

# Forward reference for `SessionState` which references `CurrentQuestion`.
SessionState.model_rebuild()
GenerateQuestionsResponse.model_rebuild()
AnswerResponse.model_rebuild()
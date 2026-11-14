import { useCallback, useEffect, useRef, useState } from "react";
import { Toaster, toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "../../src/ui/components/alert-dialog";
import { Badge } from "../../src/ui/components/badge";
import { Button } from "../../src/ui/components/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../src/ui/components/card";
import { EmptyState } from "../../src/ui/components/empty-state";
import { Field, Notice } from "../../src/ui/components/field";
import { Input } from "../../src/ui/components/input";
import { Label } from "../../src/ui/components/label";
import { Meter } from "../../src/ui/components/meter";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "../../src/ui/components/select";
import { Skeleton } from "../../src/ui/components/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../src/ui/components/tabs";
import {
  ActivityIcon as ActivityStripIcon,
  AppIcon,
  Delete02Icon,
  FlameIcon,
  GraduationCapIcon,
  Login01Icon,
  Logout01Icon,
  RefreshIcon,
} from "../../src/ui/icons";
import {
  ActivityStrip,
  DueReviews,
  MasteryBars,
  MistakeTypeChart,
  StreakFlame,
  WeaknessList,
} from "../../src/charts/progress";

import { api, auth } from "../../src/state/client";
import {
  formatResetTime,
  localTimezone,
  prefsStore,
  resolveTheme,
  setPrefs as persistPrefs,
} from "../../src/state/prefs";
import type { AuthState } from "../../src/messaging";
import type {
  AIKey,
  AIProvider,
  DifficultyMode,
  Language,
  Preferences,
  Progress,
  Theme,
  Usage,
} from "../../src/schemas";

const SIGNED_OUT: AuthState = { signedIn: false, email: null, emailVerified: false };

const LANGUAGES: { id: Language; label: string; hint?: string }[] = [
  { id: "en", label: "English" },
  // Hindi and Odia ship only once their leak-detector corpora pass (§11.4).
  { id: "hi", label: "हिन्दी", hint: "coming after review" },
  { id: "or", label: "ଓଡ଼ିଆ", hint: "coming after review" },
];

const LEVELS: { id: DifficultyMode; label: string }[] = [
  { id: "beginner", label: "Beginner" },
  { id: "intermediate", label: "Intermediate" },
];

const THEMES: { id: Theme; label: string }[] = [
  { id: "system", label: "Match the page" },
  { id: "light", label: "Light" },
  { id: "dark", label: "Dark" },
];

const PROVIDERS: { id: AIProvider; label: string }[] = [
  { id: "openai", label: "OpenAI" },
  { id: "anthropic", label: "Anthropic" },
  { id: "gemini", label: "Google Gemini" },
  { id: "groq", label: "Groq" },
];

// Convenience list, not a whitelist: Groq's catalogue turns over quickly, so
// the custom option next to it accepts any model id the account can use.
const GROQ_MODELS = [
  "llama-3.3-70b-versatile",
  "llama-3.1-8b-instant",
  "openai/gpt-oss-120b",
  "openai/gpt-oss-20b",
  "qwen/qwen3-32b",
  "moonshotai/kimi-k2-instruct",
  "meta-llama/llama-4-maverick-17b-128e-instruct",
];

const MODEL_DEFAULT = "default";
const MODEL_CUSTOM = "custom";

/** "12 runs / 5h" from the actual window rather than a hard-coded limit. */
function usageWindowLabel(usage: Usage): string {
  const start = Date.parse(usage.window_start);
  const end = Date.parse(usage.window_end);
  const hours =
    Number.isFinite(start) && Number.isFinite(end) && end > start
      ? Math.max(1, Math.round((end - start) / 3_600_000))
      : 5;
  return `${usage.question_credits_limit} runs / ${hours}h`;
}

/** Human label for the current value, rendered straight into the trigger. */
function labelOf(options: { id: string; label: string }[], value: string): string {
  return options.find((option) => option.id === value)?.label ?? value;
}

export function Popup() {
  const [authState, setAuthState] = useState<AuthState | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [planTier, setPlanTier] = useState(0);
  const [aiKey, setAiKey] = useState<AIKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [dark, setDark] = useState(false);
  const [tab, setTab] = useState("account");

  const load = useCallback(async () => {
    const stored = await prefsStore.getValue();
    setPrefs(stored);

    const state = await auth.state();
    setAuthState(state.ok ? state.data : SIGNED_OUT);
    if (!state.ok || !state.data.signedIn) return;

    // One failed panel must not blank the other two. The old Promise.all threw
    // away a successful usage read because progress happened to fail.
    const [usageRes, progressRes, meRes] = await Promise.allSettled([
      api("usage", {}),
      api("progress", {}),
      api("me", {}),
    ]);
    if (usageRes.status === "fulfilled") setUsage(usageRes.value.data);
    if (progressRes.status === "fulfilled") setProgress(progressRes.value.data);
    if (meRes.status === "fulfilled") {
      await prefsStore.setValue(meRes.value.data.preferences);
      setPrefs(meRes.value.data.preferences);
      setAuthState({
        signedIn: true,
        email: meRes.value.data.email || null,
        emailVerified: meRes.value.data.email_verified,
      });
      setPlanTier(meRes.value.data.planTier);
      setAiKey(meRes.value.data.aiKey);
      if (usageRes.status === "rejected") {
        const snapshot = meRes.value.data.usage;
        setUsage({
          ...snapshot,
          max_active_sessions: snapshot.max_active_sessions ?? 3,
          min_plan_credits: snapshot.min_plan_credits ?? 3,
        });
      }
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // The popup is its own document. Auth can change out from under it when the
  // user signs in on a browser tab (the hosted OAuth flow completes there).
  // Listen for state pushes from the service worker and re-validate on focus
  // so the "signed in / not signed in" UI never lies.
  useEffect(() => {
    const onMessage = (raw: unknown) => {
      const msg = raw as { t?: string } | undefined;
      if (msg?.t === "auth.changed") void load();
    };
    chrome.runtime.onMessage.addListener(onMessage as any);

    const onFocus = () => void load();
    window.addEventListener("focus", onFocus);

    return () => {
      chrome.runtime.onMessage.removeListener(onMessage as any);
      window.removeEventListener("focus", onFocus);
    };
  }, [load]);

  // Land on the most useful tab once we know whether there is an account.
  useEffect(() => {
    setTab(authState?.signedIn ? "progress" : "account");
  }, [authState?.signedIn]);

  // The popup is its own document, so it has to resolve the theme itself —
  // only the content script toggles `.dark` on the overlay's shadow host.
  const theme = prefs?.theme;
  useEffect(() => {
    if (!theme) return;
    const apply = () => {
      const next = resolveTheme(theme);
      document.documentElement.classList.toggle("dark", next);
      setDark(next);
    };
    apply();
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);

  async function save(patch: Partial<Preferences>) {
    const next = await persistPrefs(patch);
    setPrefs(next);
    try {
      await api("preferences", { body: patch });
    } catch {
      toast("Saved on this device. It will sync when you are back online.");
    }
  }

  // Render the skeleton until auth resolves, not just until prefs do. Prefs
  // load first, so gating on them alone painted a "Not signed in" panel for a
  // beat even with a valid session, which invited a second click.
  if (!prefs || authState === null) return <PopupSkeleton />;

  const signedIn = authState?.signedIn === true;

  return (
    <div className="flex max-h-[600px] w-[22rem] flex-col overflow-y-auto overflow-x-hidden bg-background text-foreground">
      <header className="sticky top-0 z-10 flex h-11 shrink-0 items-center gap-2 border-b border-border bg-card px-3.5">
        <AppIcon icon={GraduationCapIcon} size={16} className="shrink-0 text-primary" />
        <h1 className="text-sm font-semibold tracking-[-0.01em]">CodeMentor</h1>
        {progress && (
          <span className="ml-auto">
            <StreakFlame days={progress.current_streak} />
          </span>
        )}
      </header>

      <Tabs value={tab} onValueChange={setTab} className="flex flex-col px-3.5 pb-3.5">
        <TabsList variant="underline">
          <TabsTrigger value="account" variant="underline">
            Account
          </TabsTrigger>
          <TabsTrigger value="progress" variant="underline">
            Progress
          </TabsTrigger>
          <TabsTrigger value="settings" variant="underline">
            Settings
          </TabsTrigger>
        </TabsList>

        <TabsContent value="account" variant="underline">
          {signedIn ? (
            <AccountCard
              email={authState?.email}
              emailVerified={authState?.emailVerified ?? false}
              usage={usage}
              planTier={planTier}
              aiKey={aiKey}
              onAiKeyChange={setAiKey}
              onSignOut={async () => {
                const res = await auth.logout();
                if (res?.ok) {
                  setAuthState(SIGNED_OUT);
                  setUsage(null);
                  setProgress(null);
                  setPlanTier(0);
                  setAiKey(null);
                }
              }}
            />
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>Not signed in</CardTitle>
                <CardDescription>
                  Sign in to save progress across problems and unlock AI features.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="pt-1">
                  <Button
                    size="sm"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      const res = await auth.login();
                      setBusy(false);
                      if (res?.ok) void load();
                      else toast("Sign-in did not complete.");
                    }}
                  >
                    <AppIcon icon={Login01Icon} size={16} />
                    Continue with GitHub
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="progress" variant="underline">
          {progress ? (
            <ProgressPanel progress={progress} />
          ) : signedIn ? (
            <EmptyState
              icon={ActivityStripIcon}
              title="Nothing to chart yet"
              description="Concept mastery, repeat mistakes, and your streak appear here once you have solved a problem."
              action={
                <Button size="sm" variant="outline" onClick={() => void load()}>
                  <AppIcon icon={RefreshIcon} size={14} />
                  Refresh
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={FlameIcon}
              title="Sign in to see your progress"
              description="Mastery, mistakes, and streaks are tied to your account so they follow you between devices."
              action={
                <Button size="sm" onClick={() => setTab("account")}>
                  <AppIcon icon={Login01Icon} size={14} />
                  Go to sign in
                </Button>
              }
            />
          )}
        </TabsContent>

        <TabsContent value="settings" variant="underline">
          <div className="flex flex-col gap-4">
            <Card>
              <CardHeader>
                <CardTitle>Learning</CardTitle>
                <CardDescription>Applies to the overlay and to anything we generate.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="pref-language">Explanation language</Label>
                  <Select
                    value={prefs.language}
                    onValueChange={(value) => void save({ language: value as Language })}
                  >
                    <SelectTrigger id="pref-language">
                      {labelOf(LANGUAGES, prefs.language)}
                    </SelectTrigger>
                    <SelectContent>
                      {LANGUAGES.map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.label}
                          {item.hint && (
                            <span className="text-[11px] text-muted-foreground">
                              {" — "}
                              {item.hint}
                            </span>
                          )}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="pref-level">Level</Label>
                  <Select
                    value={prefs.difficulty_mode}
                    onValueChange={(value) => void save({ difficulty_mode: value as DifficultyMode })}
                  >
                    <SelectTrigger id="pref-level" aria-describedby="pref-level-hint">
                      {labelOf(LEVELS, prefs.difficulty_mode)}
                    </SelectTrigger>
                    <SelectContent>
                      {LEVELS.map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p id="pref-level-hint" className="text-xs leading-relaxed text-muted-foreground">
                    Controls how much scaffolding a concept card gives you.
                  </p>
                </div>

                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="pref-theme">Theme</Label>
                  <Select
                    value={prefs.theme}
                    onValueChange={(value) => void save({ theme: value as Theme })}
                  >
                    <SelectTrigger id="pref-theme" aria-describedby="pref-theme-hint">
                      {labelOf(THEMES, prefs.theme)}
                    </SelectTrigger>
                    <SelectContent>
                      {THEMES.map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p id="pref-theme-hint" className="text-xs leading-relaxed text-muted-foreground">
                    Match the page follows whichever theme LeetCode is in.
                  </p>
                </div>

                <Field
                  label="Timezone"
                  hint={`Used for streak counting. Defaults to ${localTimezone()}.`}
                >
                  <Input
                    defaultValue={prefs.timezone}
                    key={prefs.timezone}
                    spellCheck={false}
                    className="font-mono text-xs"
                    onBlur={(event) =>
                      void save({ timezone: event.target.value.trim() || localTimezone() })
                    }
                  />
                </Field>
              </CardContent>
            </Card>

            <DeleteAccountCard
              onDeleted={() => {
                setAuthState(SIGNED_OUT);
                setUsage(null);
                setProgress(null);
              }}
            />
          </div>
        </TabsContent>
      </Tabs>

      <Toaster position="bottom-center" closeButton theme={dark ? "dark" : "light"} />
    </div>
  );
}

function PopupSkeleton() {
  return (
    <div className="flex w-[22rem] flex-col gap-3 bg-background p-3.5" aria-busy="true">
      <span className="sr-only">Loading CodeMentor</span>
      <div className="flex h-11 items-center gap-2 border-b border-border">
        <Skeleton className="size-4 rounded-md" />
        <Skeleton className="h-3.5 w-24" />
      </div>
      <div className="flex h-9 items-end gap-4">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-3 w-16" />
      </div>
      <Skeleton className="h-3 w-40" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

function AccountCard({
  email,
  emailVerified,
  usage,
  planTier,
  aiKey,
  onAiKeyChange,
  onSignOut,
}: {
  email: string | null | undefined;
  emailVerified: boolean;
  usage: Usage | null;
  planTier: number;
  aiKey: AIKey | null;
  onAiKeyChange: (next: AIKey | null) => void;
  onSignOut: () => void | Promise<void>;
}) {
  const unlimited = planTier >= 1 && aiKey !== null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Signed in</CardTitle>
        <CardDescription className="truncate font-mono text-xs">{email ?? "—"}</CardDescription>
      </CardHeader>
      <CardContent>
        {emailVerified ? (
          <Badge variant="success">Email verified</Badge>
        ) : (
          <Notice tone="warning">
            Email not verified — AI features stay read-only until it is.
          </Notice>
        )}

        {unlimited ? (
          <div className="mt-1 flex flex-col gap-1">
            <Badge variant="success">Unlimited with your key</Badge>
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              AI runs use your {PROVIDERS.find((item) => item.id === aiKey.provider)?.label}
              {" "}key, so they are not counted against question credits.
            </p>
          </div>
        ) : (
          usage && (
            <Meter
              label={usageWindowLabel(usage)}
              used={usage.question_credits_used}
              total={usage.question_credits_limit}
              resetLabel={`Resets at ${formatResetTime(usage.window_end, localTimezone())}`}
              className="mt-1"
            />
          )
        )}

        <AiKeySection aiKey={aiKey} onChange={onAiKeyChange} />

        <div className="pt-1">
          <Button variant="outline" size="sm" onClick={() => void onSignOut()}>
            <AppIcon icon={Logout01Icon} size={16} />
            Sign out
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function AiKeySection({
  aiKey,
  onChange,
}: {
  aiKey: AIKey | null;
  onChange: (next: AIKey | null) => void;
}) {
  const [provider, setProvider] = useState<AIProvider>("openai");
  const [modelChoice, setModelChoice] = useState(MODEL_DEFAULT);
  const [customModel, setCustomModel] = useState("");
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  // `saving` only disables the button after the next render, so a fast double
  // click can enter `save` twice. The ref is set synchronously and is the real
  // lock; the state only drives the label.
  const savingRef = useRef(false);

  useEffect(() => {
    if (!aiKey) return;
    setProvider(aiKey.provider);
    if (aiKey.model && GROQ_MODELS.includes(aiKey.model)) {
      setModelChoice(aiKey.model);
    } else if (aiKey.model) {
      setModelChoice(MODEL_CUSTOM);
      setCustomModel(aiKey.model);
    } else {
      setModelChoice(MODEL_DEFAULT);
    }
  }, [aiKey]);

  const modelForSave =
    provider !== "groq"
      ? null
      : modelChoice === MODEL_CUSTOM
        ? customModel.trim() || null
        : modelChoice === MODEL_DEFAULT
          ? null
          : modelChoice;

  function changeProvider(next: AIProvider) {
    setProvider(next);
    if (next !== "groq") {
      setModelChoice(MODEL_DEFAULT);
      setCustomModel("");
    }
  }

  async function save() {
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try {
      const trimmed = key.trim();
      if (trimmed.length < 8) {
        toast("Paste a complete API key first.");
        return;
      }
      // Guard: you must be signed in to associate a key with your account.
      const state = await auth.state();
      if (!state.ok || !state.data.signedIn) {
        toast("Sign in before saving an API key.");
        return;
      }
      const res = await api("aiKeyPut", {
        body: { provider, api_key: trimmed, model: modelForSave },
      });
      // A 200 from the write is not proof of a stored credential. Read it back
      // and only then tell the learner it saved; otherwise a silent write
      // failure looks like the key was accepted and then ignored.
      const stored = await api("aiKeyGet", {});
      if (
        !stored.data ||
        stored.data.provider !== res.data.provider ||
        stored.data.hint !== res.data.hint ||
        (stored.data.model ?? null) !== modelForSave
      ) {
        toast("The server did not save the key. Try again.");
        return;
      }
      onChange(stored.data);
      setKey("");
      toast("Key saved on the server.");
    } catch (cause: unknown) {
      // Log the fields that identify the failure; the raw object alone prints
      // as "[object Object]" and tells you nothing.
      const err = cause as { code?: string; message?: string; status?: number };
      const code = err?.code ?? "unknown";
      const message = err?.message || "Could not save that key.";
      console.error(
        `[codementor:aiKey] save failed (${code}${err?.status ? ` ${err.status}` : ""}): ${message}`,
        cause,
      );
      toast(code === "unauthorized" ? "Sign in expired. Sign in again." : message);
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  async function remove() {
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try {
      await api("aiKeyDelete", {});
      onChange(null);
      toast("Key removed.");
    } catch {
      toast("Could not remove that key.");
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  return (
    <div className="mt-3 flex flex-col gap-1.5 border-t border-border pt-3">
      <Label htmlFor="ai-provider">Your AI key</Label>

      {aiKey ? (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-foreground">
              {PROVIDERS.find((item) => item.id === aiKey.provider)?.label ?? aiKey.provider}
              <span className="ml-1.5 font-mono text-muted-foreground">••••{aiKey.hint}</span>
            </span>
            <Button variant="ghost" size="sm" disabled={saving} onClick={() => void remove()}>
              Remove
            </Button>
          </div>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Stored encrypted. Requests use this key and never fall back to ours.
            {aiKey.model ? ` Model: ${aiKey.model}.` : ""}
          </p>
        </div>
      ) : (
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Optional. Add your own provider key to keep AI runs on your account.
        </p>
      )}

      <Select value={provider} onValueChange={(value) => changeProvider(value as AIProvider)}>
        <SelectTrigger id="ai-provider">
          {PROVIDERS.find((item) => item.id === provider)?.label ?? provider}
        </SelectTrigger>
        <SelectContent>
          {PROVIDERS.map((item) => (
            <SelectItem key={item.id} value={item.id}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        Choose the provider that issued this key — one provider's key is rejected by another.
      </p>

      {provider === "groq" && (
        <>
          <Label htmlFor="ai-model">Model</Label>
          <Select
            value={modelChoice}
            onValueChange={(value) => {
              setModelChoice(value);
              if (value !== MODEL_CUSTOM) setCustomModel("");
            }}
          >
            <SelectTrigger id="ai-model">
              {modelChoice === MODEL_CUSTOM
                ? "Custom model id"
                : modelChoice === MODEL_DEFAULT
                  ? "Default (llama-3.3-70b-versatile)"
                  : modelChoice}
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={MODEL_DEFAULT}>
                Default (llama-3.3-70b-versatile)
              </SelectItem>
              {GROQ_MODELS.map((id) => (
                <SelectItem key={id} value={id}>
                  {id}
                </SelectItem>
              ))}
              <SelectItem value={MODEL_CUSTOM}>Custom model id…</SelectItem>
            </SelectContent>
          </Select>
          {modelChoice === MODEL_CUSTOM && (
            <Input
              value={customModel}
              spellCheck={false}
              autoComplete="off"
              placeholder="e.g. openai/gpt-oss-120b"
              className="font-mono text-xs"
              onChange={(event) => setCustomModel(event.target.value)}
            />
          )}
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Must be a model id Groq serves to this key. Leave on Default to use the
            built-in choice.
          </p>
        </>
      )}

      <div className="flex gap-1.5">
        <Input
          type="password"
          value={key}
          spellCheck={false}
          autoComplete="off"
          placeholder={aiKey ? "Replace key" : "sk-…"}
          className="font-mono text-xs"
          onChange={(event) => setKey(event.target.value)}
        />
        <Button size="sm" disabled={saving || key.trim().length < 8} onClick={() => void save()}>
          {saving ? "Saving…" : "Save"}
        </Button>
      </div>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        Never sent back to this extension after saving.
      </p>
    </div>
  );
}

function ProgressPanel({ progress }: { progress: Progress }) {
  return (
    <div className="flex flex-col gap-4 [&>*:not(:first-child)]:border-t [&>*:not(:first-child)]:border-border [&>*:not(:first-child)]:pt-4">
      <section>
        <SectionHeading>Concept mastery</SectionHeading>
        <MasteryBars progress={progress} />
      </section>

      <section>
        <SectionHeading>Weak areas</SectionHeading>
        <WeaknessList progress={progress} />
      </section>

      <section>
        <SectionHeading>Mistakes by type</SectionHeading>
        <MistakeTypeChart progress={progress} />
      </section>

      <section>
        <SectionHeading>Last 8 weeks</SectionHeading>
        <ActivityStrip progress={progress} />
      </section>

      <section>
        <SectionHeading>Review queue</SectionHeading>
        <DueReviews count={progress.due_reviews} />
      </section>
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-2 text-[11px] font-medium tracking-[0.06em] text-muted-foreground uppercase">
      {children}
    </h2>
  );
}

function DeleteAccountCard({ onDeleted }: { onDeleted: () => void }) {
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  const armed = confirm.trim().toUpperCase() === "DELETE";

  async function destroy() {
    setDeleting(true);
    try {
      await api("meDelete", {});
      await auth.logout();
      setOpen(false);
      setConfirm("");
      onDeleted();
      toast("Account deleted.");
    } catch {
      setDeleting(false);
      toast("Could not delete the account. Nothing was changed.");
    }
  }

  return (
    <Card className="border-destructive/35">
      <CardHeader>
        <CardTitle>Delete account</CardTitle>
        <CardDescription>
          Removes your sessions, attempts, mistake journal, and saved cards. This cannot be undone.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <AlertDialog open={open} onOpenChange={setOpen}>
          <AlertDialogTrigger asChild>
            <Button variant="outline" size="sm" className="text-destructive hover:bg-destructive-subtle hover:text-destructive-subtle-foreground">
              <AppIcon icon={Delete02Icon} size={16} />
              Delete my account
            </Button>
          </AlertDialogTrigger>

          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete your CodeMentor account?</AlertDialogTitle>
              <AlertDialogDescription>
                Everything is removed with it: your sessions, attempts, mistake journal, and saved
                cards. There is no copy afterwards, so type DELETE to confirm.
              </AlertDialogDescription>
            </AlertDialogHeader>

            <Field label="Type DELETE to confirm">
              <Input
                value={confirm}
                spellCheck={false}
                autoComplete="off"
                className="font-mono text-xs"
                placeholder="DELETE"
                onChange={(event) => setConfirm(event.target.value)}
              />
            </Field>

            <AlertDialogFooter>
              <AlertDialogCancel>Keep my account</AlertDialogCancel>
              <AlertDialogAction
                disabled={!armed || deleting}
                onClick={(event) => {
                  event.preventDefault();
                  void destroy();
                }}
              >
                {deleting ? "Deleting…" : "Delete permanently"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </CardContent>
    </Card>
  );
}
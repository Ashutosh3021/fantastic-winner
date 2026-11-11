import { Button } from "../components/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/card";
import { Notice } from "../components/field";
import { AppIcon, Alert01Icon, RefreshIcon, WifiDisconnected01Icon } from "../icons";
import type { ApiError } from "../../schemas";
import { strings } from "../../i18n/strings";
import { useLearnerStore } from "../../state/learner";

/**
 * Error card (§21).
 *
 * Every error has a stable code, a human sentence, and a next step. We never
 * show a stack trace or a raw provider error, and we never blame the learner —
 * `ip_budget` in particular is shared by housemates and campuses.
 *
 * The code is shown in Geist Mono because it is the one string a learner might
 * quote back to us in a bug report.
 */
export function ErrorCard({
  error,
  onRetry,
  children,
}: {
  error: ApiError;
  onRetry?: () => void;
  children?: React.ReactNode;
}) {
  const language = useLearnerStore((s) => s.language);
  const t = strings(language);
  const offline = error.code === "network_error" || error.code === "timeout";
  const updated = error.code === "context_invalidated";

  const body =
    error.code === "ip_budget"
      ? "You've used a lot of CodeMentor on this network. Try again in a few minutes."
      : error.message;

  return (
    <Card className="border-destructive/35">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-destructive">
          {offline ? (
            <AppIcon icon={WifiDisconnected01Icon} size={16} />
          ) : (
            <AppIcon icon={Alert01Icon} size={16} />
          )}
          {offline
            ? t.networkErrorBody
            : updated
              ? "CodeMentor was updated"
              : "Something interrupted that"}
        </CardTitle>
        <p className="font-mono text-[11px] text-muted-foreground/80">{error.code}</p>
      </CardHeader>

      <CardContent>
        <p className="text-sm leading-relaxed">{body}</p>

        {offline && <Notice tone="info">{t.offlineBody}</Notice>}

        {updated && (
          <div className="pt-1">
            <Button size="sm" onClick={() => window.location.reload()}>
              <AppIcon icon={RefreshIcon} size={14} />
              Reload page
            </Button>
          </div>
        )}

        {error.code === "credits_exhausted" && (
          <Notice tone="warning">{t.creditsExhaustedBody}</Notice>
        )}

        {error.reset_at && (
          <p className="text-[11px] text-muted-foreground">
            Resets at{" "}
            <span className="font-mono tabular-nums">
              {new Date(error.reset_at).toLocaleTimeString()}
            </span>
            .
          </p>
        )}

        {children}

        {onRetry && !updated && (
          <div className="pt-1">
            <Button variant="outline" size="sm" onClick={onRetry}>
              <AppIcon icon={RefreshIcon} size={14} />
              {t.retry}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
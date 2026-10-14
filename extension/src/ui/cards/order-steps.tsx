import { ListBox, ListBoxItem, useDragAndDrop } from "react-aria-components";

import { Button } from "../components/button";
import { AppIcon, ArrowDown01Icon, ArrowUp01Icon, GripVerticalIcon } from "../icons";
import { cn } from "../../lib/utils";

/**
 * The "order the steps" answer type.
 *
 * Built on React Aria Components for real accessibility: the list is a
 * `listbox` with roving focus, drag and drop is announced, and every drag has a
 * keyboard equivalent — the explicit move up / move down buttons, which is the
 * path a keyboard or screen-reader user actually takes.
 *
 * Split into its own module so React Aria only loads when this question type
 * is actually shown.
 */

export type Step = { id: string; text: string };

type Props = {
  steps: Step[];
  orderedSteps: number[];
  disabled: boolean;
  onChange: (order: number[]) => void;
};

export function OrderSteps({ steps, orderedSteps, disabled, onChange }: Props) {
  const { dragAndDropHooks } = useDragAndDrop({
    getItems: (keys) => Array.from(keys).map((key) => ({ type: "step", id: String(key) })),
    onDrop: (event) => {
      // `target` is a union; only an item target carries the key we dropped onto.
      if (!("key" in event.target)) return;
      const dragged = event.items.find((item) => "id" in item)?.id;
      if (dragged === undefined) return;

      const from = orderedSteps.indexOf(Number(dragged));
      const to = orderedSteps.indexOf(Number(event.target.key));
      if (from < 0 || to < 0 || from === to) return;

      const next = [...orderedSteps];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved!);
      onChange(next);
    },
  });

  function move(index: number, delta: number) {
    const next = [...orderedSteps];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target]!, next[index]!];
    onChange(next);
  }

  return (
    <ListBox
      aria-label="Reorderable steps"
      selectionMode="none"
      items={steps}
      dragAndDropHooks={dragAndDropHooks}
      className="flex flex-col gap-1.5"
    >
      {(item) => {
        const index = orderedSteps.indexOf(Number(item.id));
        const position = index + 1;
        return (
          <ListBoxItem
            textValue={item.text}
            className={cn(
              "flex items-center gap-2 rounded-lg border border-border bg-card p-2 text-sm",
              "transition-[border-color,background-color] duration-[var(--duration-micro)] ease-out",
              "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25 focus-visible:outline-none",
              "data-[dragging]:opacity-60",
              disabled && "opacity-60",
            )}
          >
            <AppIcon
              icon={GripVerticalIcon}
              size={16}
              className="shrink-0 cursor-grab text-muted-foreground/70"
            />
            <span
              aria-hidden
              className="w-4 shrink-0 text-center font-mono text-xs tabular-nums text-muted-foreground"
            >
              {position}
            </span>
            <span className="min-w-0 flex-1 leading-snug">{item.text}</span>
            <span className="flex shrink-0 gap-0.5">
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Move "${item.text}" up`}
                disabled={disabled || index <= 0}
                onClick={() => move(index, -1)}
              >
                <AppIcon icon={ArrowUp01Icon} size={14} />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Move "${item.text}" down`}
                disabled={disabled || index >= orderedSteps.length - 1}
                onClick={() => move(index, 1)}
              >
                <AppIcon icon={ArrowDown01Icon} size={14} />
              </Button>
            </span>
          </ListBoxItem>
        );
      }}
    </ListBox>
  );
}
"use client";

import { useState, useEffect, useCallback } from "react";
import toast from "react-hot-toast";

// ── Types ──────────────────────────────────────────────────────────────────

interface QuickReply {
  label: string;
  value: string;
}

interface FlowStep {
  slot: string;
  prompt_text: string;
  quick_replies: QuickReply[] | null;
  optional: boolean;
  _new?: boolean; // client-only flag for newly added steps
}

interface Flow {
  flow_key: string;
  intent: string | null;
  is_active?: boolean;
  intro_text: string;
  abort_confirmation: string;
  completion_text_template: string;
  steps: FlowStep[];
  _source?: string;
  updated_at?: string | null;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function newBlankStep(): FlowStep {
  return { slot: "", prompt_text: "", quick_replies: [], optional: false, _new: true };
}

// ── Small sub-components ───────────────────────────────────────────────────

function IconBtn({
  title,
  onClick,
  className = "",
  children,
}: {
  title: string;
  onClick: () => void;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={`inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 ${className}`}
    >
      {children}
    </button>
  );
}

function QuickRepliesEditor({
  replies,
  onChange,
}: {
  replies: QuickReply[];
  onChange: (next: QuickReply[]) => void;
}) {
  const update = (idx: number, field: keyof QuickReply, val: string) => {
    const next = replies.map((r, i) => (i === idx ? { ...r, [field]: val } : r));
    onChange(next);
  };
  const remove = (idx: number) => onChange(replies.filter((_, i) => i !== idx));
  const add = () => onChange([...replies, { label: "", value: "" }]);

  return (
    <div className="space-y-1.5">
      <span className="text-xs font-medium text-slate-500">Quick replies</span>
      {replies.length === 0 && (
        <p className="text-xs italic text-slate-400">No quick replies — click + to add one.</p>
      )}
      {replies.map((qr, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            type="text"
            placeholder="Label shown to user"
            className="min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={qr.label}
            onChange={(e) => update(i, "label", e.target.value)}
          />
          <span className="shrink-0 text-slate-300">→</span>
          <input
            type="text"
            placeholder="Machine value"
            className="min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm font-mono text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={qr.value}
            onChange={(e) => update(i, "value", e.target.value)}
          />
          <IconBtn title="Remove reply" onClick={() => remove(i)} className="hover:text-red-500">
            <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 fill-current"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.8" fill="none" strokeLinecap="round"/></svg>
          </IconBtn>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="mt-1 flex items-center gap-1 rounded-md border border-dashed border-slate-300 px-3 py-1.5 text-xs text-slate-500 hover:border-blue-400 hover:text-blue-600"
      >
        <span className="text-base leading-none">+</span> Add quick reply
      </button>
    </div>
  );
}

// ── New-flow modal ────────────────────────────────────────────────────────

const BLANK_FLOW: Omit<Flow, "flow_key"> = {
  intent: "",
  is_active: true,
  intro_text: "",
  abort_confirmation: "No problem! Let me know if you need help with anything else.",
  completion_text_template: "",
  steps: [],
};

function NewFlowModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (key: string) => void;
}) {
  const [flowKey, setFlowKey] = useState("");
  const [intent, setIntent] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  const slugify = (v: string) =>
    v.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "");

  const handleCreate = async () => {
    const key = slugify(flowKey.trim());
    if (!key) { toast.error("Flow key is required"); return; }
    setIsCreating(true);
    try {
      const body: Record<string, unknown> = { ...BLANK_FLOW };
      if (intent.trim()) body.intent = intent.trim();
      const res = await fetch(`/api/flows/${key}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      toast.success(`Flow "${key}" created`);
      onCreated(key);
    } catch (e: unknown) {
      toast.error(`Create failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-base font-semibold text-slate-900">Create new flow</h2>

        <label className="mb-3 block">
          <span className="mb-1 block text-xs font-medium text-slate-500">
            Flow key <span className="text-red-500">*</span>
            <span className="ml-1 font-normal opacity-60">(snake_case, e.g. check_balance)</span>
          </span>
          <input
            type="text"
            autoFocus
            className="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="my_new_flow"
            value={flowKey}
            onChange={(e) => setFlowKey(slugify(e.target.value))}
          />
        </label>

        <label className="mb-5 block">
          <span className="mb-1 block text-xs font-medium text-slate-500">
            Intent tag <span className="font-normal opacity-60">(optional)</span>
          </span>
          <input
            type="text"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. check_balance"
            value={intent}
            onChange={(e) => setIntent(e.target.value)}
          />
        </label>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleCreate}
            disabled={isCreating}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {isCreating ? "Creating…" : "Create flow"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── FlowsPanel ─────────────────────────────────────────────────────────────

export function FlowsPanel() {
  const [flows, setFlows] = useState<Flow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<Flow | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isReloading, setIsReloading] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [showNewModal, setShowNewModal] = useState(false);

  // Fetch flow list
  const fetchFlows = useCallback(async (selectKey?: string) => {
    setIsLoading(true);
    try {
      const res = await fetch("/api/flows");
      if (!res.ok) throw new Error(await res.text());
      const data: Flow[] = await res.json();
      setFlows(data);
      const target = selectKey ?? selected;
      if (target) {
        const found = data.find((f) => f.flow_key === target);
        if (found) { setSelected(target); setDraft(structuredClone(found)); }
      } else if (data.length > 0) {
        setSelected(data[0].flow_key);
        setDraft(structuredClone(data[0]));
      }
    } catch {
      toast.error("Could not load flows");
    } finally {
      setIsLoading(false);
    }
  }, [selected]);

  useEffect(() => {
    fetchFlows();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectFlow = (key: string) => {
    const f = flows.find((f) => f.flow_key === key);
    if (f) {
      setSelected(key);
      setDraft(structuredClone(f));
    }
  };

  // ── Draft mutations ──────────────────────────────────────────────────────

  const setDraftField = (field: keyof Flow, value: unknown) =>
    setDraft((d) => (d ? { ...d, [field]: value } : d));

  const updateStep = (idx: number, patch: Partial<FlowStep>) =>
    setDraft((d) => {
      if (!d) return d;
      const steps = d.steps.map((s, i) => (i === idx ? { ...s, ...patch } : s));
      return { ...d, steps };
    });

  const deleteStep = (idx: number) =>
    setDraft((d) => d ? { ...d, steps: d.steps.filter((_, i) => i !== idx) } : d);

  const addStep = () =>
    setDraft((d) => d ? { ...d, steps: [...d.steps, newBlankStep()] } : d);

  const moveStep = (idx: number, dir: -1 | 1) =>
    setDraft((d) => {
      if (!d) return d;
      const steps = [...d.steps];
      const to = idx + dir;
      if (to < 0 || to >= steps.length) return d;
      [steps[idx], steps[to]] = [steps[to], steps[idx]];
      return { ...d, steps };
    });

  // ── Save ─────────────────────────────────────────────────────────────────

  const handleSave = async () => {
    if (!draft) return;

    // Validate new steps have a slot name
    const badStep = draft.steps.find((s) => s._new && !s.slot.trim());
    if (badStep !== undefined) {
      toast.error("Each new step needs a slot name.");
      return;
    }

    setIsSaving(true);
    try {
      const body = {
        is_active: draft.is_active,
        intent: draft.intent || null,
        intro_text: draft.intro_text,
        abort_confirmation: draft.abort_confirmation,
        completion_text_template: draft.completion_text_template,
        steps: draft.steps.map(({ _new: _, ...s }) => ({
          slot: s.slot,
          prompt_text: s.prompt_text,
          quick_replies: s.quick_replies?.length ? s.quick_replies : null,
          optional: s.optional,
        })),
      };
      const res = await fetch(`/api/flows/${draft.flow_key}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      toast.success("Flow saved");
      await fetchFlows(draft.flow_key);
    } catch (e: unknown) {
      toast.error(`Save failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIsSaving(false);
    }
  };

  // ── Delete / reset flow ───────────────────────────────────────────────────

  const handleDeleteFlow = async () => {
    if (!draft) return;
    const isPythonDefault = draft._source === "python_default";
    const msg = isPythonDefault
      ? `"${draft.flow_key}" is defined in Python code. This will only remove any DB text overrides — the flow will revert to its default text. Continue?`
      : `Delete flow "${draft.flow_key}"? This cannot be undone.`;
    if (!window.confirm(msg)) return;
    try {
      // Mark inactive + clear all text fields to "reset" a Python-default flow,
      // or set is_active=false for a pure DB flow.
      const body = isPythonDefault
        ? { is_active: true, intro_text: null, abort_confirmation: null, completion_text_template: null, steps: [] }
        : { is_active: false };
      const res = await fetch(`/api/flows/${draft.flow_key}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      toast.success(isPythonDefault ? "Flow reset to defaults" : "Flow deactivated");
      setSelected(null);
      setDraft(null);
      await fetchFlows();
    } catch (e: unknown) {
      toast.error(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  // ── Reload bot ───────────────────────────────────────────────────────────

  const handleReloadBot = async () => {
    setIsReloading(true);
    try {
      const res = await fetch("/api/reload-flows", { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      toast.success(`Bot reloaded — ${data.rows_applied ?? 0} override(s) applied`);
    } catch (e: unknown) {
      toast.error(`Reload failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIsReloading(false);
    }
  };

  // ── Render ───────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center text-slate-400">
        Loading flows…
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden">
      {/* New-flow modal */}
      {showNewModal && (
        <NewFlowModal
          onClose={() => setShowNewModal(false)}
          onCreated={async (key) => {
            setShowNewModal(false);
            await fetchFlows(key);
          }}
        />
      )}

      {/* Left: flow list */}
      <aside className="flex w-52 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="flex-1 overflow-y-auto p-3 space-y-1">
          {flows.map((f) => (
            <button
              key={f.flow_key}
              type="button"
              onClick={() => selectFlow(f.flow_key)}
              className={`w-full rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                selected === f.flow_key
                  ? "bg-blue-600 font-semibold text-white"
                  : "text-slate-700 hover:bg-slate-100"
              }`}
            >
              <span className="block truncate font-medium">
                {f.flow_key.replace(/_/g, " ")}
              </span>
              {f.intent && (
                <span className="block truncate text-xs opacity-70">{f.intent}</span>
              )}
              {f.is_active === false && (
                <span className="mt-0.5 inline-block rounded bg-red-100 px-1 text-[10px] text-red-600">
                  inactive
                </span>
              )}
            </button>
          ))}
        </div>
        {/* New flow button pinned at bottom */}
        <div className="shrink-0 border-t border-slate-100 p-3">
          <button
            type="button"
            onClick={() => setShowNewModal(true)}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-slate-300 py-2 text-sm text-slate-500 hover:border-blue-400 hover:text-blue-600"
          >
            <span className="text-base leading-none">+</span> New Flow
          </button>
        </div>
      </aside>

      {/* Right: editor */}
      {draft ? (
        <div className="flex min-w-0 flex-1 flex-col overflow-y-auto bg-slate-50 p-5 gap-5">

          {/* ── Header ── */}
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="flex-1 text-lg font-semibold text-slate-900">
              {draft.flow_key.replace(/_/g, " ")}
            </h2>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-600">
              <input
                type="checkbox"
                className="h-4 w-4 rounded"
                checked={draft.is_active ?? true}
                onChange={(e) => setDraftField("is_active", e.target.checked)}
              />
              Active
            </label>
            <button
              type="button"
              onClick={handleReloadBot}
              disabled={isReloading}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-60"
            >
              {isReloading ? "Reloading…" : "Reload Bot"}
            </button>
            <button
              type="button"
              onClick={handleDeleteFlow}
              className="rounded-lg border border-red-200 bg-white px-3 py-1.5 text-sm text-red-600 shadow-sm hover:bg-red-50"
              title={draft._source === "python_default" ? "Reset DB overrides" : "Deactivate flow"}
            >
              {draft._source === "python_default" ? "Reset" : "Delete"}
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={isSaving}
              className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-60"
            >
              {isSaving ? "Saving…" : "Save"}
            </button>
          </div>

          {draft.updated_at && (
            <p className="-mt-3 text-xs text-slate-400">
              Last saved: {new Date(draft.updated_at).toLocaleString()}
            </p>
          )}

          {/* ── Flow-level texts ── */}
          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-4">
            <h3 className="text-sm font-semibold text-slate-700">Flow Texts</h3>

            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500">
                Intent tag
                <span className="ml-1 font-normal opacity-60">(used by intent classifier to trigger this flow)</span>
              </span>
              <input
                type="text"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="e.g. download_statement"
                value={draft.intent ?? ""}
                onChange={(e) => setDraftField("intent", e.target.value)}
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500">Intro / greeting</span>
              <textarea
                rows={3}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={draft.intro_text}
                onChange={(e) => setDraftField("intro_text", e.target.value)}
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500">Abort confirmation</span>
              <textarea
                rows={2}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={draft.abort_confirmation}
                onChange={(e) => setDraftField("abort_confirmation", e.target.value)}
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500">
                Completion template{" "}
                <span className="font-normal opacity-60">(used when KB augment is off)</span>
              </span>
              <textarea
                rows={5}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={draft.completion_text_template}
                onChange={(e) => setDraftField("completion_text_template", e.target.value)}
              />
            </label>
          </section>

          {/* ── Steps ── */}
          <section className="space-y-3">
            <div className="flex items-center gap-2">
              <h3 className="flex-1 text-sm font-semibold text-slate-700">
                Steps ({draft.steps.length})
              </h3>
              <button
                type="button"
                onClick={addStep}
                className="flex items-center gap-1 rounded-lg border border-dashed border-slate-300 px-3 py-1.5 text-xs text-slate-500 hover:border-blue-400 hover:text-blue-600"
              >
                <span className="text-sm leading-none">+</span> Add step
              </button>
            </div>

            {draft.steps.length === 0 && (
              <p className="rounded-lg border border-dashed border-slate-200 p-4 text-center text-sm text-slate-400">
                No steps yet — click &ldquo;Add step&rdquo; above.
              </p>
            )}

            {draft.steps.map((step, idx) => (
              <div
                key={`${step.slot}-${idx}`}
                className={`rounded-xl border bg-white p-4 shadow-sm space-y-4 ${
                  step._new ? "border-blue-300 ring-1 ring-blue-200" : "border-slate-200"
                }`}
              >
                {/* Step header row */}
                <div className="flex items-center gap-2">
                  {step._new ? (
                    <input
                      type="text"
                      placeholder="slot_name (e.g. date_range)"
                      className="flex-1 rounded-md border border-slate-300 px-2 py-1 font-mono text-xs text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      value={step.slot}
                      onChange={(e) => updateStep(idx, { slot: e.target.value })}
                    />
                  ) : (
                    <span className="flex-1 font-mono text-xs font-semibold uppercase tracking-wide text-slate-500">
                      slot: {step.slot}
                    </span>
                  )}

                  {/* Optional toggle */}
                  <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-500">
                    <input
                      type="checkbox"
                      className="h-3.5 w-3.5 rounded"
                      checked={step.optional}
                      onChange={(e) => updateStep(idx, { optional: e.target.checked })}
                    />
                    optional
                  </label>

                  {/* Move up */}
                  <IconBtn title="Move up" onClick={() => moveStep(idx, -1)}>
                    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 fill-none stroke-current" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M8 12V4M4 7l4-4 4 4"/>
                    </svg>
                  </IconBtn>

                  {/* Move down */}
                  <IconBtn title="Move down" onClick={() => moveStep(idx, 1)}>
                    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 fill-none stroke-current" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M8 4v8M4 9l4 4 4-4"/>
                    </svg>
                  </IconBtn>

                  {/* Delete step */}
                  <IconBtn
                    title="Delete step"
                    onClick={() => deleteStep(idx)}
                    className="hover:bg-red-50 hover:text-red-500"
                  >
                    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 fill-none stroke-current" strokeWidth="1.8" strokeLinecap="round">
                      <path d="M2 4h12M6 4V2h4v2M5 4l1 9h4l1-9"/>
                    </svg>
                  </IconBtn>
                </div>

                {/* Prompt */}
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-500">Prompt</span>
                  <textarea
                    rows={2}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    value={step.prompt_text}
                    onChange={(e) => updateStep(idx, { prompt_text: e.target.value })}
                  />
                </label>

                {/* Quick replies */}
                <QuickRepliesEditor
                  replies={step.quick_replies ?? []}
                  onChange={(qrs) => updateStep(idx, { quick_replies: qrs })}
                />
              </div>
            ))}
          </section>

          {/* Bottom save shortcut */}
          <div className="flex justify-end pb-4">
            <button
              type="button"
              onClick={handleSave}
              disabled={isSaving}
              className="rounded-lg bg-blue-600 px-6 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-60"
            >
              {isSaving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center text-slate-400 text-sm">
          Select a flow to edit
        </div>
      )}
    </div>
  );
}

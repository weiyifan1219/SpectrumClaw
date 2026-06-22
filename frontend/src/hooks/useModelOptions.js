import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchLlmOptions } from "../lib/api.js";
import { loadModelSelection, saveModelSelection } from "../lib/modelSelection.js";

const DEFAULT_REASONING_OPTIONS = [
  { id: "off", label: "Off", description: "关闭推理" },
  { id: "low", label: "Low", description: "更快响应" },
  { id: "medium", label: "Medium", description: "均衡推理" },
  { id: "high", label: "High", description: "更强推理" },
  { id: "xhigh", label: "XHigh", description: "复杂任务" },
];

const DEFAULT_MODEL_OPTIONS = [
  {
    id: "deepseek:deepseek-v4-pro",
    provider: "deepseek",
    provider_label: "DeepSeek",
    api_type: "openai_compatible",
    model: "deepseek-v4-pro",
    label: "DeepSeek Pro",
    configured: true,
    supports_reasoning: true,
    reasoning_efforts: ["off", "low", "medium", "high", "xhigh"],
    current: true,
  },
  {
    id: "deepseek:deepseek-v4-flash",
    provider: "deepseek",
    provider_label: "DeepSeek",
    api_type: "openai_compatible",
    model: "deepseek-v4-flash",
    label: "DeepSeek Flash",
    configured: true,
    supports_reasoning: true,
    reasoning_efforts: ["off", "low", "medium", "high", "xhigh"],
    current: false,
  },
];

function normalizeModelOption(item) {
  if (!item || !item.model) return null;
  const provider = item.provider || "openai_compatible";
  const model = item.model;
  return {
    id: item.id || `${provider}:${model}`,
    provider,
    provider_label: item.provider_label || provider,
    api_type: item.api_type || "openai_compatible",
    model,
    label: item.label || model,
    configured: Boolean(item.configured),
    supports_reasoning: Boolean(item.supports_reasoning),
    reasoning_efforts: Array.isArray(item.reasoning_efforts) ? item.reasoning_efforts : [],
    current: Boolean(item.current),
  };
}

function matchSavedModel(saved, options) {
  if (!saved) return null;
  return options.find((m) => m.id === saved)
    || options.find((m) => m.model === saved)
    || null;
}

export function useModelOptions({ onModelChange } = {}) {
  const [modelOptions, setModelOptions] = useState(DEFAULT_MODEL_OPTIONS);
  const [reasoningOptions, setReasoningOptions] = useState(DEFAULT_REASONING_OPTIONS);
  const [modelId, setModelId] = useState(() => {
    const saved = loadModelSelection();
    const matched = matchSavedModel(saved, DEFAULT_MODEL_OPTIONS);
    return matched?.id ?? saved ?? null;
  });
  const [thinkingEnabled, setThinkingEnabled] = useState(false);
  const [reasoningEffort, setReasoningEffort] = useState("off");

  const activeModel = useMemo(
    () => matchSavedModel(modelId, modelOptions)
      ?? modelOptions.find((m) => m.current)
      ?? modelOptions[0]
      ?? DEFAULT_MODEL_OPTIONS[0],
    [modelOptions, modelId]
  );

  const availableReasoningOptions = useMemo(() => {
    const allowed = activeModel?.reasoning_efforts?.length
      ? new Set(activeModel.reasoning_efforts)
      : new Set(reasoningOptions.map((r) => r.id));
    return reasoningOptions.filter((r) => allowed.has(r.id));
  }, [activeModel, reasoningOptions]);

  const activeReasoningId = thinkingEnabled ? reasoningEffort : "off";
  const activeReasoningOption = availableReasoningOptions.find((r) => r.id === activeReasoningId)
    ?? availableReasoningOptions[0]
    ?? DEFAULT_REASONING_OPTIONS[0];

  const canUseReasoning = Boolean(activeModel?.supports_reasoning && availableReasoningOptions.length);
  const reasoningButtonLabel = activeModel?.supports_reasoning
    ? activeReasoningOption.label
    : "Off";

  useEffect(() => {
    let active = true;
    async function loadOptions() {
      try {
        const data = await fetchLlmOptions();
        if (!active) return;
        const options = (data.models || []).map(normalizeModelOption).filter(Boolean);
        const nextReasoning = Array.isArray(data.reasoning_options) && data.reasoning_options.length
          ? data.reasoning_options
          : DEFAULT_REASONING_OPTIONS;
        if (!options.length) return;
        setReasoningOptions(nextReasoning);
        setModelOptions(options);
        setModelId((current) => {
          const saved = loadModelSelection();
          const matched = matchSavedModel(saved, options) || matchSavedModel(current, options);
          const next = matched || options.find((m) => m.current) || options[0];
          saveModelSelection(next.id);
          return next.id;
        });
      } catch {
        /* keep fallback model options */
      }
    }
    loadOptions();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    onModelChange?.(activeModel?.label ?? activeModel?.model ?? "Model");
  }, [activeModel, onModelChange]);

  useEffect(() => {
    if (!canUseReasoning && thinkingEnabled) {
      setThinkingEnabled(false);
    }
    if (!canUseReasoning && reasoningEffort !== "off") {
      setReasoningEffort("off");
    }
    if (canUseReasoning && !availableReasoningOptions.some((r) => r.id === reasoningEffort)) {
      const fallback = availableReasoningOptions.find((r) => r.id === "high") ?? availableReasoningOptions[0];
      if (fallback) setReasoningEffort(fallback.id);
    }
  }, [availableReasoningOptions, canUseReasoning, reasoningEffort, thinkingEnabled]);

  const handleModelChange = useCallback((id) => {
    setModelId(id);
    saveModelSelection(id);
  }, []);

  return {
    activeModel,
    availableReasoningOptions,
    canUseReasoning,
    handleModelChange,
    modelId,
    modelOptions,
    reasoningButtonLabel,
    reasoningEffort,
    setReasoningEffort,
    setThinkingEnabled,
    thinkingEnabled,
  };
}

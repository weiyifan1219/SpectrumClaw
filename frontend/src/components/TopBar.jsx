import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Command, Menu, Search, X } from "lucide-react";
import { navSections, systemSignals } from "../data/mockData.js";

const allDestinations = navSections.flatMap((section) =>
  section.items.map((item) => ({ ...item, section: section.label }))
);

export default function TopBar({ activeId, crumbs, pageMeta, modelLabel, onNavigate, onToggleSidebar }) {
  const [quickOpen, setQuickOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const quickRef = useRef(null);
  const inputRef = useRef(null);
  const signals = systemSignals.map((signal) =>
    signal.label === "Model" ? { ...signal, value: modelLabel ?? signal.value } : signal
  );

  const destinations = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return allDestinations;
    return allDestinations.filter((item) =>
      `${item.label} ${item.chinese || ""} ${item.section}`.toLowerCase().includes(keyword)
    );
  }, [query]);

  useEffect(() => {
    const onKeyDown = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setQuickOpen((open) => !open);
      }
      if (event.key === "Escape") setQuickOpen(false);
    };
    const onPointerDown = (event) => {
      if (quickRef.current && !quickRef.current.contains(event.target)) setQuickOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, []);

  useEffect(() => {
    if (!quickOpen) return;
    setQuery("");
    setHighlightedIndex(0);
    window.requestAnimationFrame(() => inputRef.current?.focus());
  }, [quickOpen]);

  useEffect(() => { setHighlightedIndex(0); }, [query]);

  const chooseDestination = (id) => {
    onNavigate(id);
    setQuickOpen(false);
  };

  const handleQuickKeyDown = (event) => {
    if (!destinations.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlightedIndex((index) => (index + 1) % destinations.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightedIndex((index) => (index - 1 + destinations.length) % destinations.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      chooseDestination(destinations[Math.min(highlightedIndex, destinations.length - 1)].id);
    }
  };

  return (
    <header className="topbar">
      <button className="topbar-menu" type="button" onClick={onToggleSidebar} aria-label="打开导航">
        <Menu size={19} />
      </button>

      <div className="topbar-context" title={pageMeta?.description || crumbs.join(" / ")}>
        <span className="topbar-context-kicker">{pageMeta?.kicker || crumbs.slice(0, -1).join(" · ")}</span>
        <span className="topbar-context-line"><strong>{pageMeta?.title || crumbs.at(-1)}</strong><small>{pageMeta?.description}</small></span>
      </div>

      <div className="topbar-actions">
        <div className="page-toolbar-slot" id="page-toolbar-slot" aria-label="当前页面操作" />
        <div className="quick-switch" ref={quickRef}>
          <button
            className="quick-switch-trigger"
            type="button"
            onClick={() => setQuickOpen((open) => !open)}
            aria-expanded={quickOpen}
            aria-haspopup="dialog"
          >
            <Search size={14} />
            <span>快速导航</span>
            <kbd><Command size={10} />K</kbd>
          </button>

          {quickOpen && (
            <section className="quick-switch-panel" role="dialog" aria-label="快速导航">
              <div className="quick-switch-search">
                <Search size={15} />
                <input
                  ref={inputRef}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={handleQuickKeyDown}
                  placeholder="搜索页面或能力…"
                  aria-label="搜索页面"
                />
                <button type="button" onClick={() => setQuickOpen(false)} aria-label="关闭快速导航"><X size={15} /></button>
              </div>
              <div className="quick-switch-list">
                {destinations.map((item, index) => {
                  const Icon = item.icon;
                  const active = item.id === activeId;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={`${active ? "active" : ""} ${index === highlightedIndex ? "highlighted" : ""}`}
                      onMouseEnter={() => setHighlightedIndex(index)}
                      onClick={() => chooseDestination(item.id)}
                    >
                      <span className="quick-switch-icon"><Icon size={16} /></span>
                      <span><strong>{item.label}</strong><small>{item.section} · {item.chinese}</small></span>
                      {active && <Check size={14} />}
                    </button>
                  );
                })}
                {!destinations.length && <p className="quick-switch-empty">没有匹配的页面</p>}
              </div>
              <footer><span><kbd>↑</kbd><kbd>↓</kbd> 选择</span><span><kbd>Enter</kbd> 打开</span><span><kbd>Esc</kbd> 关闭</span></footer>
            </section>
          )}
        </div>

        <div className="signal-row" aria-label="系统状态摘要">
          {signals.map((signal) => (
            <div className="signal" key={signal.label} data-tone={signal.tone} aria-label={`${signal.label}: ${signal.value}`}>
              <span className="k">{signal.label}</span>
              <span className="v">{signal.value}</span>
            </div>
          ))}
        </div>
      </div>
    </header>
  );
}

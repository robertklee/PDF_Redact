import { useMarks } from "../marks";
import { type SidebarTab, useSearch } from "../search";
import { MarksPanel } from "./MarksPanel";
import { PropertiesPanel } from "./PropertiesPanel";
import { SearchPanel } from "./SearchPanel";

const TABS: { id: SidebarTab; label: string }[] = [
  { id: "marks", label: "Marks" },
  { id: "search", label: "Search" },
];

export function Sidebar() {
  const tab = useSearch((s) => s.tab);
  const setTab = useSearch((s) => s.setTab);
  const markCount = useMarks((s) => s.marks.length);
  const hasSelection = useMarks((s) => s.selection.length > 0);
  const hitCount = useSearch((s) => (s.status === "done" ? s.hits.length : 0));
  const counts: Record<SidebarTab, number> = { marks: markCount, search: hitCount };

  return (
    <aside className="sidebar">
      <div className="tabs" role="tablist" aria-label="Side panel">
        {TABS.map((t) => (
          <button
            key={t.id}
            id={`tab-${t.id}`}
            role="tab"
            aria-selected={tab === t.id}
            aria-controls={`tabpanel-${t.id}`}
            className={tab === t.id ? "active" : ""}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {counts[t.id] > 0 && <span className="count">{counts[t.id]}</span>}
          </button>
        ))}
      </div>
      <div className="tab-panel" id={`tabpanel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === "marks" ? <MarksPanel /> : <SearchPanel />}
      </div>
      {/* Search needs the room; the appearance of new marks is set from the Marks tab. */}
      {(tab === "marks" || hasSelection) && <PropertiesPanel />}
    </aside>
  );
}

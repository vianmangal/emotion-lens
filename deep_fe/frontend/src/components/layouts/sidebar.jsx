export default function Sidebar({ activeTab, setActiveTab }) {
  const tabs = [
    { id: "safety", label: "Live Safety", icon: "◎" },
    { id: "upload", label: "Upload Image", icon: "↑" },
    { id: "webcam", label: "Webcam Snapshot", icon: "◉" },
  ];

  const tabClassName = (tabId) =>
    `rounded-xl border text-[10px] font-semibold uppercase tracking-wider transition-all duration-200 md:text-xs ${
      activeTab === tabId
        ? "bg-white border-white text-black font-bold shadow-[0_0_15px_rgba(255,255,255,0.1)]"
        : "bg-transparent border-zinc-800 text-zinc-400 hover:text-white hover:border-zinc-700 hover:bg-zinc-950"
    }`;

  return (
    <>
      <div className="sticky top-0 z-30 border-b border-zinc-900 bg-black/95 px-4 py-3 backdrop-blur md:hidden">
        <div className="grid grid-cols-3 gap-2">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex min-w-0 items-center justify-center gap-1.5 px-2 py-2.5 ${tabClassName(tab.id)}`}
            >
              <span>{tab.icon}</span>
              <span className="truncate">{tab.label}</span>
            </button>
          ))}
        </div>
      </div>

      <aside className="hidden w-60 shrink-0 border-r border-zinc-900 bg-black md:flex md:min-h-screen md:flex-col md:select-none md:font-mono">
        <div className="border-b border-zinc-900 p-6">
          <div className="text-[10px] font-semibold tracking-[0.2em] text-zinc-500 uppercase">
            WORKSPACE
          </div>
        </div>

        <nav className="flex-1 space-y-2 p-4">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex w-full items-center gap-3 px-4 py-3.5 ${tabClassName(tab.id)}`}
            >
              <span>
                {tab.icon} {tab.label}
              </span>
            </button>
          ))}
        </nav>

        <div className="border-t border-zinc-900 px-4 py-5 text-[9px] text-zinc-600">
          <div>{['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname) ? 'LOCAL COMPUTER' : 'HOSTED DEMO'}</div>
        </div>
      </aside>
    </>
  );
}

interface PlaceholderPanelProps {
  title: string;
  /** Short statement of what this section will do when it is built. */
  note?: string;
}

export function PlaceholderPanel({ title, note }: PlaceholderPanelProps) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2 className="panel-title">{title}</h2>

        {/*
          The tab reads as a finished workspace section, but the content is
          a stub. Saying so plainly stops the client asking whether it is
          broken, and makes the roadmap visible from inside the app.
        */}
        <span className="chip chip-info">Coming soon</span>
      </div>

      <div className="panel-body">
        <p className="page-sub">
          {note ??
            "This module is not built yet. The underlying data model is in place; the interface will be added in a later release."}
        </p>
      </div>
    </section>
  );
}

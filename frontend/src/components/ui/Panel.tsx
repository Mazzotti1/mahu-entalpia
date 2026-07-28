import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  children: ReactNode;
}

export function Panel({ title, children }: PanelProps) {
  return (
    <section className="mb-3 rounded-[10px] border border-gray-200 bg-white p-3">
      <h2 className="mb-2 text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

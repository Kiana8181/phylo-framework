"use client";

import { Card } from "@/components/ui/card";

export default function ResultsSummary({
  stats,
  cloneRows,
}: {
  stats: any;
  cloneRows: Array<{ id: string; seqs: any }>;
}) {
  return (
    <section className="space-y-4">
      <h3 className="text-lg font-medium">Results</h3>

      {/* KPIs */}
      {stats && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Card className="p-4">
            <div className="text-xs text-muted-foreground">Clones</div>
            <div className="text-2xl font-semibold">
              {stats.n_clones ?? "-"}
            </div>
          </Card>
          <Card className="p-4">
            <div className="text-xs text-muted-foreground">Trees</div>
            <div className="text-2xl font-semibold">{stats.n_trees ?? "-"}</div>
          </Card>
          <Card className="p-4">
            <div className="text-xs text-muted-foreground">Sequences</div>
            <div className="text-2xl font-semibold">
              {stats.total_seqs ?? "-"}
            </div>
          </Card>
        </div>
      )}

      {/* Clones table */}
      <Card className="p-0 overflow-hidden">
        <div className="px-4 py-3 border-b">
          <h4 className="font-medium">Clone summary</h4>
        </div>
        {cloneRows.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40">
                <tr>
                  <th className="px-3 py-2 text-left">Clone ID</th>
                  <th className="px-3 py-2 text-left">Seqs</th>
                </tr>
              </thead>
              <tbody>
                {cloneRows.map((r, i) => (
                  <tr key={i} className="border-t">
                    <td className="px-3 py-2">{r.id}</td>
                    <td className="px-3 py-2">{r.seqs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-4 text-sm text-muted-foreground">
            No clone metadata found.
          </div>
        )}
      </Card>
    </section>
  );
}

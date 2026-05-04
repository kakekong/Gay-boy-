export default function OperationPage() {
  const stages = ["Receiving", "Warehousing", "QC", "Packaging", "Delivery"];
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Operation — Work Order Board</h1>
      <div className="grid grid-cols-5 gap-3">
        {stages.map((s) => (
          <div key={s} className="bg-white border rounded p-3 min-h-[160px]">
            <div className="text-sm font-medium mb-2">{s}</div>
            <div className="text-xs text-slate-400">No work orders</div>
          </div>
        ))}
      </div>
    </div>
  );
}

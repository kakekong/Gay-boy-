export default function PurchasingPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Purchasing</h1>
      <div className="grid grid-cols-5 gap-2">
        {["PR", "RFQ", "Supplier PO", "Goods Receipt", "QC"].map((s) => (
          <div key={s} className="bg-white border rounded p-3 text-sm">
            <div className="font-medium">{s}</div>
            <div className="text-xs text-slate-500">Pipeline view</div>
          </div>
        ))}
      </div>
      <p className="text-sm text-slate-500">
        Track each document in the purchasing chain: PR → RFQ → Supplier PO → GR → QC → Payment.
      </p>
    </div>
  );
}

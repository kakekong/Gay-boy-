import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, ClipboardList, Send, PackageCheck, CheckCircle2,
  Construction, ArrowRight,
} from "lucide-react";
import clsx from "clsx";

const STAGES: Record<string, {
  label: string;
  icon: typeof ClipboardList;
  tone: string;
  description: string;
  nextSteps: string[];
}> = {
  pr: {
    label: "Purchase Request",
    icon: ClipboardList,
    tone: "bg-amber-50 text-amber-700",
    description:
      "An internal team requests materials they need. This is the first step of procurement — a PR doesn't commit money, it just signals demand.",
    nextSteps: [
      "Engineer / sales raises a PR against a project.",
      "Purchasing reviews, fans it out to suppliers as an RFQ.",
      "When prices come back, PR is closed and a supplier PO is issued.",
    ],
  },
  rfq: {
    label: "Request for Quotation",
    icon: Send,
    tone: "bg-blue-50 text-blue-700",
    description:
      "We ask multiple suppliers what they'd charge for the items on a PR. The cheapest / fastest / most reliable wins the resulting PO.",
    nextSteps: [
      "Send the same line items to a shortlist of suppliers.",
      "Collect quoted lead times + prices into a comparison table.",
      "Director picks the winner, that supplier gets a PO.",
    ],
  },
  gr: {
    label: "Goods Receipt",
    icon: PackageCheck,
    tone: "bg-cyan-50 text-cyan-700",
    description:
      "Materials physically arrive from the supplier. Receiving confirms quantities match the PO before they go to QC and warehousing.",
    nextSteps: [
      "Compare delivered qty vs. PO qty — flag shortages.",
      "Generate a GR document, attach signed delivery note.",
      "Hand off to QC for incoming inspection.",
    ],
  },
  qc: {
    label: "QC (incoming)",
    icon: CheckCircle2,
    tone: "bg-violet-50 text-violet-700",
    description:
      "Quality check for materials we bought from suppliers. Fail rate feeds back into supplier ratings on the Purchasing page.",
    nextSteps: [
      "Inspect against spec, log pass / fail counts.",
      "Reject batches feed back to the supplier as a claim.",
      "Accepted batches flow into Warehousing on the Operation board.",
    ],
  },
};

export default function PurchasingStagePage() {
  const { stage } = useParams<{ stage: string }>();
  const nav = useNavigate();
  const meta = STAGES[stage ?? ""];

  if (!meta) {
    return (
      <div className="card p-10 text-center">
        <div className="mt-3 font-semibold">Unknown procurement stage</div>
        <p className="text-sm muted mt-1">"{stage}" isn't a stage we know about.</p>
        <button className="btn-ghost mt-4" onClick={() => nav("/purchasing")}>
          <ArrowLeft size={14} /> Back to Purchasing
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <Link
        to="/purchasing"
        className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700"
      >
        <ArrowLeft size={14} /> Back to Purchasing
      </Link>

      <div className="card p-6 lg:p-8">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
              <meta.icon size={13} className="text-brand-600" /> Procurement stage
            </div>
            <h1 className="text-2xl font-semibold tracking-tight mt-0.5">{meta.label}</h1>
          </div>
          <span className={clsx("chip text-xs font-semibold", meta.tone)}>
            {meta.label}
          </span>
        </div>
        <p className="text-sm muted mt-3 max-w-2xl">{meta.description}</p>
      </div>

      <div className="card p-5 lg:p-6 space-y-3">
        <div className="flex items-center gap-2">
          <Construction size={16} className="text-amber-600" />
          <span className="font-semibold">Coming soon</span>
        </div>
        <p className="text-sm muted max-w-2xl">
          This step isn't wired up in this build. The director-owned
          supplier PO flow at <Link to="/purchase-orders" className="text-brand-700 hover:underline">/purchase-orders</Link> covers procurement
          end-to-end today. When this stage ships, here's the shape it
          will take:
        </p>
        <ul className="text-sm text-ink-700 space-y-1 list-disc pl-5 max-w-2xl">
          {meta.nextSteps.map((s, i) => <li key={i}>{s}</li>)}
        </ul>
        <div className="pt-2">
          <Link
            to="/purchase-orders"
            className="btn-primary inline-flex items-center gap-1"
          >
            Go to Supplier POs <ArrowRight size={13} />
          </Link>
        </div>
      </div>
    </div>
  );
}

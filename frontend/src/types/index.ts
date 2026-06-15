export type Stage =
  | "lead" | "presentation" | "engineering" | "quotation" | "negotiation"
  | "po" | "drawing" | "purchasing" | "delivery" | "invoicing" | "payment"
  | "closed_won" | "closed_lost";

export interface Customer {
  id: string;
  company_name: string;
  industry: string;
  pic_name?: string;
  whatsapp?: string;
  stage: Stage;
  sales_pic_id?: string;
  sales_pic_name?: string | null;
  lifetime_value: number;
}

export interface Quotation {
  id: string;
  number: string;
  customer_id: string;
  status: string;
  variant: "short" | "detailed";
  discount_pct: number;
  total: number;
  valid_until?: string;
}

export interface AtRiskDeal {
  deal_id: string;
  deal_number: string;
  customer_name: string;
  risk_level: "low" | "medium" | "high";
  reasons: { factor: string; contribution: number }[];
  recommended_action: string;
  discount_pct: number;
}

export interface TopAction {
  reminder_id: string;
  customer_id: string | null;
  kind: string;
  due_at: string;
  ai_optimal_at?: string | null;
  channel: string;
  message: string | null;
  priority_score: number;
}

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
  /** The rep name the import file carried, if this customer came from one. */
  sales_rep_hint?: string | null;
  lifetime_value: number;
  /** False once deactivated — kept on file, out of the lists and pickers. */
  is_active?: boolean;
  deactivated_at?: string | null;
  deactivated_reason?: string | null;
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
  customer_name?: string | null;
  price_request_number?: string | null;
  sales_pic_name?: string | null;
  created_at?: string | null;
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

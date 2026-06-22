import { Link } from "react-router-dom";
import { useAuthStore } from "@/store/auth";

/**
 * Renders a user's name. For a director it links through to that user's
 * profile (/employees/:id) so they can drill into anyone's data from any
 * page; for everyone else it's plain text.
 */
export function UserLink({ id, name, className }: {
  id: string | null | undefined;
  name: string | null | undefined;
  className?: string;
}) {
  const role = useAuthStore((s) => s.user?.role);
  const label = name || "—";
  if (role === "director" && id) {
    return (
      <Link
        to={`/employees/${id}`}
        onClick={(e) => e.stopPropagation()}
        className={className ?? "text-brand-700 hover:underline"}
      >
        {label}
      </Link>
    );
  }
  return <span className={className}>{label}</span>;
}

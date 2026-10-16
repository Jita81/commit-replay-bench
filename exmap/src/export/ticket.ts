// exmap/src/export/ticket.ts — ticket.json and ticket.md (design §12.3). Step-zero stubs.
import type { Ticket } from "../core/types.js";
import type { ExportContext } from "./index.js";

export function ticket(ctx: ExportContext): Ticket {
  void ctx;
  throw new Error("not implemented: ticket");
}

export function ticketMarkdown(ctx: ExportContext): string {
  void ctx;
  throw new Error("not implemented: ticketMarkdown");
}

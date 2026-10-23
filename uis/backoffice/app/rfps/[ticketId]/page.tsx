import type { Metadata } from "next";
import { RfpTicketDetail } from "@/components/rfps/RfpTicketDetail";

export const metadata: Metadata = { title: "Ticket de RFP" };

interface RfpTicketPageProps {
  params: Promise<{ ticketId: string }>;
}

export default async function RfpTicketPage({ params }: RfpTicketPageProps) {
  const { ticketId } = await params;
  return <RfpTicketDetail ticketId={ticketId} />;
}

import type { Metadata } from "next";
import { RfpIntake } from "@/components/rfps/RfpIntake";

export const metadata: Metadata = { title: "Recepción de RFPs" };

export default function RfpsPage() {
  return <RfpIntake />;
}

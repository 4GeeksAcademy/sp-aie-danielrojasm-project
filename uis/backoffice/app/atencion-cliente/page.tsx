import type { Metadata } from "next";
import { SupportChat } from "@/components/customer-service/SupportChat";

export const metadata: Metadata = { title: "Atención al cliente" };

export default function CustomerServicePage() {
  return <SupportChat />;
}

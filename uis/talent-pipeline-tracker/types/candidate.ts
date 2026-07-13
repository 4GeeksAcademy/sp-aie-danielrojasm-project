export type CandidateStatus =
  | "received"
  | "in_progress"
  | "selected"
  | "discarded";

export type CandidateStage =
  | "pending"
  | "review"
  | "personal_interview"
  | "technical_interview"
  | "offer_presented";

export interface Candidate {
  id: string;
  name: string;
  email: string;
  phone: string;
  position: string;
  linkedinUrl: string;
  cvUrl: string;
  yearsExperience: number;
  status: CandidateStatus;
  stage: CandidateStage;
  appliedAt: string;
}

export interface CandidateNote {
  id: string;
  content: string;
  createdAt: string;
}

export interface CandidateFormValues {
  name: string;
  email: string;
  phone: string;
  position: string;
  linkedinUrl: string;
  cvUrl: string;
  yearsExperience: string;
  status: CandidateStatus;
  stage: CandidateStage;
  appliedAt: string;
}

export interface CandidateUpsertPayload {
  name: string;
  email: string;
  phone: string;
  position: string;
  linkedin_url: string;
  resume_url: string;
  experience_years: number;
  status: CandidateStatus;
  stage: CandidateStage;
  applied_at: string;
}

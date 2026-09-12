export type Role = 'member' | 'agent' | 'admin'
export type MoneyStatus = 'Unpaid' | 'Partially Paid' | 'Awaiting Verification' | 'Verified'

export interface CaseRecord {
  id: string
  caseNumber: string
  name: string
  initials: string
  taluk: string
  deathDate: string
  createdDate: string
  amount: number
  collected: number
  verified: number
  requiredTotal: number
  talukProgress: Array<{ id: string; name: string; required: number; collected: number; verified: number }>
  status: 'Open' | 'Closed' | 'Cancelled'
  details: string
  photoUrl?: string
  accent: string
}

export interface MemberRecord {
  id: string
  code: string
  name: string
  phone: string
  taluk: string
  membership: 'Regular' | 'Permanent'
  pending: number
  permanentVerified: number
  status: 'Active' | 'Inactive' | 'Locked' | 'Deceased'
  talukId?: string
  joinedOn?: string
  version?: number
  profileVersion?: number
  permanentAccountId?: string
  permanentTarget?: number
  permanentCollected?: number
  obligations?: Array<{ id: string; caseId: string; label: string; available: number }>
}

export interface CollectionRecord {
  id: string
  receipt: string
  memberId: string
  member: string
  caseId?: string
  label: string
  type: 'Death contribution' | 'Permanent membership'
  amount: number
  method: 'Cash' | 'UPI' | 'Bank transfer' | 'Other'
  date: string
  status: 'Recorded' | 'Batched' | 'Verified'
  collectorName?: string
}

export interface DepositRecord {
  id: string
  number: string
  agent: string
  agentPhone: string
  taluk: string
  bank: string
  bankName: string
  calculated: number
  declared: number
  submitted: string
  status: 'Draft' | 'Submitted' | 'Approved' | 'Rejected'
  collectionIds: string[]
  reference: string
  note: string
  rejectionReason?: string
  version?: number
}

export interface DueRecord {
  caseId: string
  obligationId: string
  name: string
  caseNumber: string
  required: number
  collected: number
  verified: number
}

export const formatAmount = (value: number) => new Intl.NumberFormat('en-IN', {
  maximumFractionDigits: value % 1 ? 2 : 0
}).format(value)

export const formatMoney = (value: number) => `INR ${formatAmount(value)}`

export const getMoneyStatus = (required: number, collected: number, verified: number): MoneyStatus => {
  if (collected === 0) return 'Unpaid'
  if (collected < required) return 'Partially Paid'
  if (verified < required) return 'Awaiting Verification'
  return 'Verified'
}

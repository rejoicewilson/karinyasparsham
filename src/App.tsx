import { createContext, useContext, useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { FaWhatsapp } from 'react-icons/fa6'
import {
  AlertCircle, ArrowLeft, ArrowRight, BadgeCheck, Banknote, Bell, BookOpen, CalendarDays,
  Check, CheckCircle2, ChevronDown, ChevronRight, CircleDollarSign, Clock3, Download,
  Eye, EyeOff, FileCheck2, HeartHandshake, Home, IndianRupee, Landmark,
  ListChecks, LockKeyhole, LogOut, Menu, MessageSquareText, MoreVertical, Paperclip, Pencil, Plus, Receipt,
  Search, ShieldCheck, Smartphone, UserRound, Users, WalletCards, WifiOff, X,
  XCircle, type LucideIcon
} from 'lucide-react'
import { formatAmount, formatMoney, getMoneyStatus, type CaseRecord, type CollectionRecord, type DepositRecord, type DueRecord, type MemberRecord, type Role } from './data'
import { ApiError, authApi, workspaceApi, type ApiProfile, type Workspace } from './api'

type Session = {
  id: string; role: Role; name: string; loginId: string; talukName?: string; bank?: ApiProfile['bank'];
  memberCode?: string; agent?: ApiProfile['agent']
}
type Toast = { text: string; tone?: 'success' | 'danger' }
type Notice = { id: string; title: string; body: string; time: string; unread: boolean; kind: string }
type CaseWhatsAppTracking = { caseId: string; memberId: string; status: 'OPENED' | 'SENT' | 'NOT_SENT'; updatedAt: string }
type AppData = {
  cases: CaseRecord[]; members: MemberRecord[]; memberDues: DueRecord[]; notifications: Notice[];
  taluks: Record<string, any>[]; agents: Record<string, any>[]; bankAccounts: Record<string, any>[];
  caseWhatsAppTracking: CaseWhatsAppTracking[]
}

const emptyData: AppData = { cases: [], members: [], memberDues: [], notifications: [], taluks: [], agents: [], bankAccounts: [], caseWhatsAppTracking: [] }
const DataContext = createContext<AppData>(emptyData)
const useAppData = () => useContext(DataContext)

const titleCase = (value: string) => value.toLowerCase().replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase())
const dateText = (value: string) => value ? new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium' }).format(new Date(value)) : ''
const dateTimeText = (value: string) => value ? new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : ''
const normalizeMoneyInput = (event: FormEvent<HTMLInputElement>) => {
  const input = event.currentTarget
  const normalized = input.value.replace(/^0+(?=\d)/, '')
  if (normalized !== input.value) input.value = normalized
}
const Money = ({ value }: { value: number }) => <span className="money-value"><IndianRupee aria-hidden="true" /><span>{formatAmount(value)}</span></span>
const downloadCsv = (filename: string, rows: Array<Array<string | number>>) => {
  const protect = (value: string | number) => {
    const raw = String(value)
    const safe = /^[=+@-]/.test(raw) ? `'${raw}` : raw
    return `"${safe.replaceAll('"', '""')}"`
  }
  const blob = new Blob([rows.map(row => row.map(protect).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url; link.download = filename; link.click()
  URL.revokeObjectURL(url)
}
const whatsappNumber = (phone: string) => {
  const digits = phone.replace(/\D/g, '')
  if (digits.length === 10) return `91${digits}`
  if (digits.length === 11 && digits.startsWith('0')) return `91${digits.slice(1)}`
  return digits.length >= 8 && digits.length <= 15 ? digits : ''
}
const whatsappLink = (phone: string, message: string) => {
  const number = whatsappNumber(phone)
  return number ? `https://wa.me/${number}?text=${encodeURIComponent(message)}` : ''
}
const ADMIN_WHATSAPP_NUMBER = '9447645196'
const toSession = (profile: ApiProfile): Session => ({
  id: profile.id, role: profile.role.toLowerCase() as Role, name: profile.full_name,
  loginId: profile.login_id, talukName: profile.taluk_name || undefined, bank: profile.bank,
  memberCode: profile.member_code || undefined, agent: profile.agent
})

function mapWorkspace(raw: Workspace) {
  const cases: CaseRecord[] = raw.cases.map((item, index) => ({
    id: String(item.id), caseNumber: String(item.case_number), name: String(item.deceased_name),
    initials: initials(String(item.deceased_name)), taluk: String(item.taluk_name || ''),
    deathDate: dateText(String(item.death_date)), createdDate: dateTimeText(String(item.created_at)),
    amount: Number(item.contribution_amount), collected: Number(item.collected_amount),
    verified: Number(item.verified_amount), status: titleCase(String(item.status)) as CaseRecord['status'],
    requiredTotal: Number(item.required_amount),
    talukProgress: (item.taluk_progress || []).map((progress: Record<string, any>) => ({
      id: String(progress.id), name: String(progress.name), required: Number(progress.required),
      collected: Number(progress.collected), verified: Number(progress.verified),
    })),
    details: String(item.details), photoUrl: item.photo_url ? String(item.photo_url) : undefined,
    accent: ['#8b4a3c', '#446b67', '#5a6274', '#276749'][index % 4]
  }))
  const members: MemberRecord[] = raw.members.map(item => ({
    id: String(item.id), code: String(item.member_code), ardNo: item.ard_no ? String(item.ard_no) : undefined,
    name: String(item.full_name), phone: String(item.phone || ''),
    taluk: String(item.taluk_name || ''), membership: titleCase(String(item.membership_type)) as MemberRecord['membership'],
    talukId: String(item.taluk_id), joinedOn: String(item.joined_on), version: Number(item.version),
    profileVersion: Number(item.profile_version),
    pending: Number(item.pending_amount), permanentVerified: Number(item.permanent_verified),
    status: titleCase(String(item.account_status)) as MemberRecord['status'],
    permanentAccountId: item.permanent_account_id ? String(item.permanent_account_id) : undefined,
    permanentTarget: Number(item.permanent_target), permanentCollected: Number(item.permanent_collected),
    obligations: (item.obligations || []).map((due: Record<string, any>) => ({
      id: String(due.id), caseId: String(due.case_id), label: String(due.label), available: Number(due.available_amount)
    }))
  }))
  const memberDues: DueRecord[] = raw.dues.map(item => ({
    caseId: String(item.case_id), obligationId: String(item.obligation_id),
    name: cases.find(c => c.id === String(item.case_id))?.name || String(item.label), caseNumber: String(item.case_number),
    required: Number(item.required_amount), collected: Number(item.collected_amount), verified: Number(item.verified_amount)
  }))
  const collections: CollectionRecord[] = raw.collections.map(item => ({
    id: String(item.id), receipt: String(item.receipt_number), memberId: String(item.member_id), member: String(item.member_name),
    caseId: item.case_id ? String(item.case_id) : undefined, label: String(item.label),
    type: item.collection_type === 'PERMANENT_MEMBERSHIP' ? 'Permanent membership' : 'Death contribution',
    amount: Number(item.amount), method: titleCase(String(item.method)) as CollectionRecord['method'],
    date: dateText(String(item.collected_at)), status: titleCase(String(item.status)) as CollectionRecord['status'],
    collectorName: String(item.collector_name || 'Collection agent'),
  }))
  const deposits: DepositRecord[] = raw.deposits.map(item => ({
    id: String(item.id), number: String(item.deposit_number), agent: String(item.agent_name), agentPhone: String(item.agent_phone || ''), taluk: String(item.taluk_name),
    bankName: String(item.bank_name || 'Assigned bank'),
    bank: `${item.bank_name}${item.bank_last4 ? ` •••• ${item.bank_last4}` : ''}`,
    calculated: Number(item.calculated_total), declared: Number(item.declared_deposit_amount),
    submitted: dateTimeText(String(item.submitted_at || item.created_at)), status: titleCase(String(item.status)) as DepositRecord['status'],
    collectionIds: (item.collection_ids || []).map(String), reference: String(item.bank_reference || ''), note: String(item.handover_note || ''),
    rejectionReason: item.rejection_reason ? String(item.rejection_reason) : undefined, version: Number(item.version)
  }))
  const notifications: Notice[] = raw.notifications.map(item => ({
    id: String(item.id), title: String(item.title), body: String(item.body), time: dateTimeText(String(item.created_at)),
    unread: !item.read, kind: String(item.type).includes('VERIFIED') ? 'verified' : 'case'
  }))
  const caseWhatsAppTracking: CaseWhatsAppTracking[] = (raw.case_whatsapp_tracking || []).map(item => ({
    caseId: String(item.case_id), memberId: String(item.member_id),
    status: String(item.status) as CaseWhatsAppTracking['status'], updatedAt: dateTimeText(String(item.updated_at)),
  }))
  return {
    data: { cases, members, memberDues, notifications, taluks: raw.taluks, agents: raw.agents || [], bankAccounts: raw.bank_accounts || [], caseWhatsAppTracking },
    collections, deposits, session: toSession(raw.profile)
  }
}

const pageTitles: Record<string, string> = {
  dashboard: 'Overview', cases: 'Death cases', dues: 'Outstanding', payments: 'Payment history',
  permanent: 'Account', notifications: 'Notifications', account: 'Account',
  collect: 'Payments', handovers: 'Payments', deposits: 'Payments', members: 'Members', reports: 'Reports',
  taluks: 'Organization'
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [data, setData] = useState<AppData>(emptyData)
  const [collections, setCollections] = useState<CollectionRecord[]>([])
  const [deposits, setDeposits] = useState<DepositRecord[]>([])
  const [booting, setBooting] = useState(true)
  const [passwordRequired, setPasswordRequired] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [online, setOnline] = useState(navigator.onLine)
  const [toast, setToast] = useState<Toast | null>(null)
  const navigate = useNavigate()

  const loadWorkspace = async () => {
    setLoadError('')
    try {
      const mapped = mapWorkspace(await workspaceApi.load())
      setSession(mapped.session); setData(mapped.data); setCollections(mapped.collections); setDeposits(mapped.deposits)
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Application data could not be loaded.')
      throw error
    }
  }

  useEffect(() => {
    authApi.session().then(async ({ profile }) => {
      setSession(toSession(profile)); setPasswordRequired(Boolean(profile.must_change_password))
      if (!profile.must_change_password) await loadWorkspace()
    }).catch(() => undefined).finally(() => setBooting(false))
  }, [])

  useEffect(() => {
    const on = () => setOnline(true)
    const off = () => setOnline(false)
    const expired = () => {
      setSession(null); setPasswordRequired(false); setLoadError('')
      setData(emptyData); setCollections([]); setDeposits([])
      navigate('/', { replace: true })
    }
    window.addEventListener('online', on); window.addEventListener('offline', off)
    window.addEventListener('karunya:session-expired', expired)
    return () => {
      window.removeEventListener('online', on); window.removeEventListener('offline', off)
      window.removeEventListener('karunya:session-expired', expired)
    }
  }, [navigate])

  const notify = (text: string, tone: Toast['tone'] = 'success') => {
    setToast({ text, tone }); window.setTimeout(() => setToast(null), 3200)
  }

  const login = async (loginId: string, password: string) => {
    const { profile } = await authApi.login(loginId, password)
    const next = toSession(profile); setSession(next); setPasswordRequired(Boolean(profile.must_change_password))
    if (!profile.must_change_password) await loadWorkspace()
    navigate(`/${next.role}/dashboard`)
  }

  const logout = async () => {
    await authApi.logout().catch(() => undefined)
    setSession(null); setData(emptyData); setCollections([]); setDeposits([]); navigate('/')
  }

  if (booting) return <main className="loading-screen"><img src="/logo.png" alt="" /><p>Loading secure session...</p></main>
  if (!session) return <Login onLogin={login} />
  if (passwordRequired) return <PasswordChange session={session} onComplete={async () => { setPasswordRequired(false); await loadWorkspace(); navigate(`/${session.role}/dashboard`) }} onLogout={logout} />

  return (
    <DataContext.Provider value={data}>
      {!online && <div className="offline"><WifiOff size={17} /> You are offline. Financial actions are unavailable.</div>}
      <AppShell session={session} onLogout={logout}>
        {loadError && <p className="form-error"><AlertCircle />{loadError}</p>}
        <RoleRouter
          role={session.role}
          online={online}
          collections={collections}
          setCollections={setCollections}
          deposits={deposits}
          setDeposits={setDeposits}
          notify={notify}
          reload={loadWorkspace}
          session={session}
        />
      </AppShell>
      {toast && <div className={`toast ${toast.tone === 'danger' ? 'danger' : ''}`}><CheckCircle2 size={18} />{toast.text}</div>}
    </DataContext.Provider>
  )
}

function Login({ onLogin }: { onLogin: (loginId: string, password: string) => Promise<void> }) {
  const [loginId, setLoginId] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!loginId.trim() || !password) { setError('Enter your login ID and password.'); return }
    setSubmitting(true); setError('')
    try { await onLogin(loginId.trim(), password) }
    catch (cause) { setError(cause instanceof ApiError ? cause.message : 'Unable to reach the server.') }
    finally { setSubmitting(false) }
  }

  return (
    <main className="login-page">
      <section className="login-brand">
        <strong className="malayalam-wordmark" lang="ml">കാരുണ്യസ്പർശം</strong>
        <img src="/logo.png" alt="Karunya Sparsham" />
        <div><strong>Karunya Sparsham</strong><span>Helping fund management</span></div>
      </section>
      <section className="login-panel">
        <div className="login-identity">
          <strong className="malayalam-wordmark" lang="ml">കാരുണ്യസ്പർശം</strong>
          <img src="/logo.png" alt="Karunya Sparsham" />
        </div>
        <div className="login-copy"><span className="eyebrow">SECURE ACCESS</span><h1>Welcome back</h1><p>Sign in with the login ID provided by your administrator.</p></div>
        <form onSubmit={submit}>
          <label>Login ID<input value={loginId} onChange={e => { setLoginId(e.target.value); setError('') }} autoComplete="username" placeholder="Enter your login ID" /></label>
          <label>Password<div className="password-field"><input value={password} onChange={e => { setPassword(e.target.value); setError('') }} type={show ? 'text' : 'password'} autoComplete="current-password" placeholder="Enter your password" /><button type="button" onClick={() => setShow(!show)} aria-label={show ? 'Hide password' : 'Show password'}>{show ? <EyeOff /> : <Eye />}</button></div></label>
          {error && <p className="form-error"><AlertCircle size={16} />{error}</p>}
          <button className="primary full" disabled={submitting} type="submit">{submitting ? 'Signing in…' : 'Sign in'} <ArrowRight size={18} /></button>
        </form>
        <p className="security-note"><ShieldCheck size={16} /> Your financial records are protected and auditable.</p>
      </section>
    </main>
  )
}

function PasswordChange({ session, onComplete, onLogout }: { session: Session; onComplete: () => Promise<void>; onLogout: () => void }) {
  const [password, setPassword] = useState(''), [confirm, setConfirm] = useState('')
  const [error, setError] = useState(''), [submitting, setSubmitting] = useState(false)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (password.length < 8) { setError('Use at least 8 characters.'); return }
    if (password !== confirm) { setError('Passwords do not match.'); return }
    setSubmitting(true); setError('')
    try { await authApi.changePassword(password); await onComplete() }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Password could not be changed.') }
    finally { setSubmitting(false) }
  }
  return <main className="login-page"><section className="login-brand"><img src="/logo.png" alt="Karunya Sparsham" /><div><strong>Karunya Sparsham</strong><span>Helping fund management</span></div></section><section className="login-panel"><div className="login-copy"><span className="eyebrow">FIRST SIGN IN</span><h1>Create a new password</h1><p>{session.name}, replace the temporary password before continuing.</p></div><form onSubmit={submit}><label>New password<input type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} /></label><label>Confirm password<input type="password" autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} /></label>{error && <p className="form-error"><AlertCircle />{error}</p>}<button className="primary full" disabled={submitting}>{submitting ? 'Updating…' : 'Update password'}</button><button type="button" className="secondary" onClick={onLogout}>Sign out</button></form></section></main>
}

type NavItem = { key: string; label: string; icon: LucideIcon }
const navByRole: Record<Role, NavItem[]> = {
  member: [
    { key: 'dashboard', label: 'Home', icon: Home }, { key: 'cases', label: 'Cases', icon: HeartHandshake },
    { key: 'dues', label: 'Outstanding', icon: IndianRupee }, { key: 'payments', label: 'History', icon: Receipt },
    { key: 'account', label: 'Account', icon: UserRound }
  ],
  agent: [
    { key: 'dashboard', label: 'Home', icon: Home }, { key: 'cases', label: 'Cases', icon: HeartHandshake },
    { key: 'handovers', label: 'Payments', icon: Receipt }, { key: 'members', label: 'Members', icon: Users },
    { key: 'account', label: 'Account', icon: UserRound }
  ],
  admin: [
    { key: 'dashboard', label: 'Overview', icon: Home }, { key: 'cases', label: 'Death cases', icon: HeartHandshake },
    { key: 'handovers', label: 'Collections', icon: FileCheck2 }, { key: 'members', label: 'Members', icon: Users },
    { key: 'taluks', label: 'Organization', icon: Landmark }, { key: 'reports', label: 'Reports', icon: ListChecks }
  ]
}

function AppShell({ session, onLogout, children }: { session: Session; onLogout: () => void; children: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [drawer, setDrawer] = useState(false)
  const segment = location.pathname.split('/')[2] || 'dashboard'
  const nav = navByRole[session.role]
  const { notifications } = useAppData()
  const unread = notifications.filter(item => item.unread).length
  const go = (key: string) => { navigate(`/${session.role}/${key}`); setDrawer(false); window.scrollTo(0, 0) }

  return (
    <div className={`app ${session.role}`}>
      <aside className={`sidebar ${drawer ? 'open' : ''}`}>
        <div className="side-brand"><img src="/logo.png" alt="" /><div><strong>Karunya<br />Sparsham</strong><span>Helping fund</span></div><button className="icon-btn drawer-close" onClick={() => setDrawer(false)}><X /></button></div>
        <nav>{nav.map(item => <button className={segment === item.key ? 'active' : ''} key={item.key} onClick={() => go(item.key)}><item.icon /><span>{item.label}</span></button>)}</nav>
        <div className="side-profile"><div className="avatar">{initials(session.name)}</div><div><strong>{session.name}</strong><span>{session.role}</span></div><button onClick={onLogout} aria-label="Sign out"><LogOut /></button></div>
      </aside>
      {drawer && <button className="scrim" onClick={() => setDrawer(false)} aria-label="Close menu" />}
      <div className="app-main">
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setDrawer(true)}><Menu /></button>
          <div><span>{session.role === 'member' ? `Hello, ${session.name.split(' ')[0]}` : session.role === 'agent' ? session.talukName || 'Collection agent' : 'Administration'}</span><h1>{pageTitles[segment] || 'Karunya Sparsham'}</h1></div>
          <button className="notification-btn" onClick={() => navigate(`/${session.role}/notifications`)} aria-label="Notifications"><Bell />{unread > 0 && <i>{unread}</i>}</button>
        </header>
        <main className="content">{children}</main>
      </div>
      {session.role !== 'admin' && <nav className="bottom-nav">{nav.map(item => <button className={segment === item.key ? 'active' : ''} key={item.key} onClick={() => go(item.key)}><item.icon /><span>{item.label}</span></button>)}</nav>}
    </div>
  )
}

function RoleRouter(props: {
  role: Role; online: boolean; collections: CollectionRecord[]; setCollections: (value: CollectionRecord[]) => void;
  deposits: DepositRecord[]; setDeposits: (value: DepositRecord[]) => void; notify: (message: string, tone?: Toast['tone']) => void;
  reload: () => Promise<void>; session: Session
}) {
  const { pathname } = useLocation()
  const section = pathname.split('/')[2] || 'dashboard'
  const detail = pathname.split('/')[3]

  if (section === 'notifications') return <NotificationsPage />
  if (section === 'account') return <AccountPage session={props.session} notify={props.notify} />
  if (props.role === 'member') {
    if (section === 'cases' && detail) return <CaseDetail caseId={detail} member />
    if (section === 'cases') return <CasesPage role="member" />
    if (section === 'dues') return <MemberDues />
    if (section === 'payments') return <MemberPayments collections={props.collections} />
    if (section === 'permanent') return <AccountPage session={props.session} notify={props.notify} />
    return <MemberDashboard session={props.session} />
  }
  if (props.role === 'agent') {
    if (section === 'collect' || section === 'handovers' || section === 'deposits') return <AgentPayments collections={props.collections} deposits={props.deposits} session={props.session} />
    if (section === 'members' && detail) return <MemberDetail id={detail} collections={props.collections} />
    if (section === 'members') return <MembersPage role="agent" />
    if (section === 'cases' && detail) return <CaseDetail caseId={detail} />
    if (section === 'cases') return <CasesPage role="agent" />
    return <AgentDashboard collections={props.collections} deposits={props.deposits} />
  }
  if (section === 'cases' && detail) return <CaseDetail caseId={detail} admin />
  if (section === 'cases') return <AdminCases online={props.online} notify={props.notify} reload={props.reload} />
  if (section === 'handovers' || section === 'deposits') return <AdminDeposits deposits={props.deposits} setDeposits={props.setDeposits} collections={props.collections} setCollections={props.setCollections} online={props.online} notify={props.notify} reload={props.reload} />
  if (section === 'members') return <MembersPage role="admin" reload={props.reload} notify={props.notify} />
  if (section === 'taluks') return <TaluksPage reload={props.reload} notify={props.notify} />
  if (section === 'reports') return <ReportsPage />
  return <AdminDashboard deposits={props.deposits} />
}

function MemberDashboard({ session }: { session: Session }) {
  const navigate = useNavigate()
  const { cases, memberDues, members } = useAppData(); const member = members[0]
  const toGive = memberDues.reduce((sum, due) => sum + due.required - due.collected, 0)
  const permanentCollected = member?.permanentCollected || 0
  const permanentVerified = member?.permanentVerified || 0
  const awaiting = memberDues.reduce((sum, due) => sum + due.collected - due.verified, 0) + Math.max(permanentCollected - permanentVerified, 0)
  const target = member?.permanentTarget || 0
  return <div className="page-stack">
    <section className="member-summary band-green">
      <div><span>Amount to give agent</span><strong>{<Money value={toGive} />}</strong><small>{memberDues.filter(d => d.required > d.collected).length} open obligations · {<Money value={awaiting} />} awaiting verification</small></div>
      <button onClick={() => navigate('/member/dues')}>View outstanding <ChevronRight size={18} /></button>
    </section>
    <SectionHeading title="Permanent membership" action="View progress" onAction={() => navigate('/member/account')} />
    <section className="progress-section">
      <div className="progress-copy"><div><span>Verified</span><strong>{<Money value={permanentVerified} />}</strong></div><div><span>Target</span><strong>{<Money value={target} />}</strong></div></div>
      <Progress value={target ? permanentVerified / target * 100 : 0} />
      <p><BadgeCheck size={17} /> {<Money value={Math.max(target - permanentVerified, 0)} />} remaining to become permanent</p>
    </section>
    <SectionHeading title="Recent helping requests" action="See all" onAction={() => navigate('/member/cases')} />
    <div className="case-list">{cases.slice(0, 2).map(item => <CaseCard key={item.id} item={item} onClick={() => navigate(`/member/cases/${item.id}`)} memberDue={memberDues.find(d => d.caseId === item.id)} />)}</div>
    {session.agent && <section className="agent-contact"><div className="avatar dark">{initials(session.agent.full_name)}</div><div><span>Your collection agent</span><strong>{session.agent.full_name}</strong><small>{session.talukName}{session.agent.phone ? ` · ${session.agent.phone}` : ''}</small></div><button disabled={!session.agent.phone} title={session.agent.phone ? `Call ${session.agent.full_name}` : 'Agent phone number is not configured'} aria-label="Contact agent" onClick={() => { if (session.agent?.phone) window.location.href = `tel:${session.agent.phone}` }}><MessageSquareText /></button></section>}
  </div>
}

function AgentDashboard({ collections, deposits }: { collections: CollectionRecord[]; deposits: DepositRecord[] }) {
  const navigate = useNavigate()
  const { cases, members } = useAppData()
  const unbatched = collections.filter(c => c.status === 'Recorded').reduce((sum, c) => sum + c.amount, 0)
  const totalOutstanding = members.reduce((sum, member) => sum + member.pending + Math.max(
    (member.permanentAccountId ? member.permanentTarget || 0 : 0) - (member.permanentCollected || 0), 0
  ), 0)
  return <div className="page-stack">
    <section className="metric-grid agent-metrics">
      <Metric icon={Users} label="Assigned members" value={String(members.length)} />
      <Metric icon={IndianRupee} label="Total pending" value={<Money value={totalOutstanding} />} tone="red" />
      <Metric icon={WalletCards} label="Awaiting handover" value={<Money value={unbatched} />} tone="amber" />
      <Metric icon={Clock3} label="Awaiting receipt" value={String(deposits.filter(d => d.status === 'Submitted').length)} tone="blue" />
    </section>
    <section className="readonly-banner"><ShieldCheck /><div><strong>View-only access</strong><span>Collection entries are recorded and verified by the administrator.</span></div></section>
    <SectionHeading title="Current cases" action="View cases" onAction={() => navigate('/agent/cases')} />
    <div className="case-list">{cases.slice(0, 2).map(item => <CaseCard agent key={item.id} item={item} onClick={() => navigate(`/agent/cases/${item.id}`)} />)}</div>
    <SectionHeading title="Payment history" action="View all" onAction={() => navigate('/agent/handovers')} />
    <div className="list-surface">{deposits.slice(0, 2).map(d => <DepositRow key={d.id} deposit={d} />)}</div>
  </div>
}

function AgentPayments({ collections, deposits, session }: { collections: CollectionRecord[]; deposits: DepositRecord[]; session: Session }) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'All' | 'Verified' | 'Awaiting'>('All')
  const term = query.trim().toLowerCase()
  const visible = collections.filter(item => {
    const matchesStatus = filter === 'All' || (filter === 'Verified' ? item.status === 'Verified' : item.status !== 'Verified')
    return matchesStatus && (!term || item.member.toLowerCase().includes(term) || item.label.toLowerCase().includes(term) || item.receipt.toLowerCase().includes(term))
  })
  const ownBatches = deposits.filter(item => item.agent === session.name)
  return <div className="page-stack">
    <section className="readonly-banner"><ShieldCheck /><div><strong>Payment records</strong><span>These records are maintained by the administrator and cannot be changed from an agent account.</span></div></section>
    <div className="toolbar"><SearchBox value={query} onChange={setQuery} placeholder="Search member, case, or receipt" /></div>
    <div className="filter-row">{(['All', 'Verified', 'Awaiting'] as const).map(value => <button key={value} className={`chip ${filter === value ? 'active' : ''}`} onClick={() => setFilter(value)}>{value}</button>)}</div>
    {visible.length ? <div className="payment-list">{visible.map(item => <article key={item.id}><div className={`payment-icon ${item.status.toLowerCase()}`}>{item.status === 'Verified' ? <Check /> : <Clock3 />}</div><div><strong>{item.member}</strong><span>{item.label} · {item.receipt}</span><small>{item.method} · {item.date}</small></div><div><strong><Money value={item.amount} /></strong><Status value={item.status === 'Verified' ? 'Verified' : 'Awaiting Verification'} /></div></article>)}</div> : <div className="empty-review"><Receipt /><h3>No payments found</h3><p>Payment records entered by the administrator will appear here.</p></div>}
    {ownBatches.length > 0 && <><SectionHeading title="Historical handovers" /><div className="list-surface deposits-full">{ownBatches.map(item => <DepositRow key={item.id} deposit={item} />)}</div></>}
  </div>
}

function AdminDashboard({ deposits }: { deposits: DepositRecord[] }) {
  const navigate = useNavigate()
  const { cases, members, taluks } = useAppData()
  const talukTotals = cases.flatMap(item => item.talukProgress).reduce((totals, item) => {
    const current = totals.get(item.id) || { required: 0, collected: 0 }
    current.required += item.required; current.collected += item.collected; totals.set(item.id, current)
    return totals
  }, new Map<string, { required: number; collected: number }>())
  return <div className="page-stack admin-page">
    <div className="admin-heading"><div><span className="eyebrow">LIVE DATABASE</span><h2>Administration overview</h2><p>Current organization and collection status.</p></div><button className="primary" onClick={() => navigate('/admin/cases?create=1')}><Plus /> New death case</button></div>
    <section className="metric-grid admin-metrics">
      <Metric icon={Users} label="Active members" value={String(members.filter(m => m.status === 'Active').length)} detail={`${members.filter(m => m.membership === 'Permanent').length} permanent`} />
      <Metric icon={HeartHandshake} label="Open cases" value={String(cases.filter(c => c.status === 'Open').length)} detail={`${cases.length} total cases`} tone="red" />
      <Metric icon={Clock3} label="Awaiting verification" value={<Money value={cases.reduce((sum, item) => sum + item.collected - item.verified, 0)} />} detail="Collected, pending approval" tone="amber" />
      <Metric icon={IndianRupee} label="Outstanding dues" value={<Money value={members.reduce((sum, item) => sum + item.pending, 0)} />} detail={`${taluks.length} taluks`} tone="blue" />
    </section>
    <div className="admin-columns">
      <section><SectionHeading title="Collection records" action="View all" onAction={() => navigate('/admin/handovers')} /><div className="list-surface">{deposits.slice(0, 5).map(d => <DepositRow key={d.id} deposit={d} admin onClick={() => navigate('/admin/handovers')} />)}</div></section>
      <section><SectionHeading title="Taluk collection progress" action="View report" onAction={() => navigate('/admin/reports')} />{taluks.length ? <div className="taluk-progress">{taluks.map(item => { const total = talukTotals.get(String(item.id)); const percent = total?.required ? total.collected / total.required * 100 : 0; return <div key={String(item.id)}><div><strong>{String(item.name)}</strong><span>{Math.round(percent)}% collected</span></div><Progress value={percent} /></div> })}</div> : <p className="subtle">No taluks have been configured.</p>}</section>
    </div>
    <SectionHeading title="Recent death cases" action="View register" onAction={() => navigate('/admin/cases')} />
    <div className="case-list admin-cases">{cases.slice(0, 3).map(item => <CaseCard key={item.id} item={item} onClick={() => navigate(`/admin/cases/${item.id}`)} />)}</div>
  </div>
}

function CasesPage({ role }: { role: Role }) {
  const navigate = useNavigate(); const { cases, memberDues } = useAppData()
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'All' | 'Open' | 'Closed'>('All')
  const visible = cases.filter(item => {
    const matchesStatus = filter === 'All' || item.status === filter
    const term = query.trim().toLowerCase()
    return matchesStatus && (!term || item.caseNumber.toLowerCase().includes(term) || item.name.toLowerCase().includes(term) || item.taluk.toLowerCase().includes(term))
  })
  return <div className="page-stack"><SearchBox value={query} onChange={setQuery} placeholder="Search cases or member name" /><div className="filter-row">{(['All', 'Open', 'Closed'] as const).map(status => <button key={status} className={`chip ${filter === status ? 'active' : ''}`} onClick={() => setFilter(status)}>{status === 'All' ? 'All cases' : status}</button>)}</div>{visible.length ? <div className="case-list">{visible.map(item => <CaseCard key={item.id} item={item} memberDue={role === 'member' ? memberDues.find(d => d.caseId === item.id) : undefined} agent={role === 'agent'} onClick={() => navigate(`/${role}/cases/${item.id}`)} />)}</div> : <div className="empty-review"><HeartHandshake /><h3>No cases found</h3><p>Try another search or status filter.</p></div>}</div>
}

function AdminCases({ online, notify, reload }: { online: boolean; notify: (message: string) => void; reload: () => Promise<void> }) {
  const { search } = useLocation()
  const [modal, setModal] = useState(() => new URLSearchParams(search).get('create') === '1')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'All' | CaseRecord['status']>('All')
  const { cases } = useAppData()
  const navigate = useNavigate()
  const visible = cases.filter(item => {
    const matchesStatus = filter === 'All' || item.status === filter
    const term = query.trim().toLowerCase()
    return matchesStatus && (!term || item.caseNumber.toLowerCase().includes(term) || item.name.toLowerCase().includes(term) || item.taluk.toLowerCase().includes(term))
  })
  return <div className="page-stack"><div className="toolbar"><SearchBox value={query} onChange={setQuery} placeholder="Search case number or member" /><button className="primary" disabled={!online} onClick={() => setModal(true)}><Plus /> Create case</button></div><div className="filter-row">{(['All', 'Open', 'Closed', 'Cancelled'] as const).map(status => <button key={status} className={`chip ${filter === status ? 'active' : ''}`} onClick={() => setFilter(status)}>{status === 'All' ? 'All cases' : status}</button>)}</div>{visible.length ? <div className="case-list admin-cases">{visible.map(item => <CaseCard key={item.id} item={item} onClick={() => navigate(`/admin/cases/${item.id}`)} />)}</div> : <div className="empty-review"><HeartHandshake /><h3>No cases found</h3><p>Try another search or status filter.</p></div>}{modal && <CreateCaseModal onClose={() => setModal(false)} onPublish={async caseId => { setModal(false); await reload(); notify('Death case published. WhatsApp messages are ready.'); navigate(`/admin/cases/${caseId}`) }} />}</div>
}

function CaseDetail({ caseId, member = false, admin = false }: { caseId: string; member?: boolean; admin?: boolean }) {
  const navigate = useNavigate(); const { cases, memberDues } = useAppData(); const item = cases.find(c => c.id === caseId)
  if (!item) return <div className="empty-review"><HeartHandshake /><h3>Case not found</h3></div>
  const due = memberDues.find(d => d.caseId === item.id)
  return <div className="page-stack detail-page"><button className="back-link" onClick={() => navigate(-1)}><ArrowLeft /> Back to cases</button><section className="case-hero"><CasePhoto item={item} large /><div><span className="case-number">{item.caseNumber}</span><h2>{item.name}</h2><p>{item.details}</p><div className="meta-row"><span><CalendarDays /> {item.deathDate}</span><span><MapPinIcon /> {item.taluk}</span><Status value={item.status} /></div></div></section>{member && due ? <><SectionHeading title="Your contribution" /><section className="contribution-detail"><div><span>Required</span><strong>{<Money value={due.required} />}</strong></div><div><span>Collected</span><strong>{<Money value={due.collected} />}</strong></div><div><span>Verified</span><strong>{<Money value={due.verified} />}</strong></div><div><span>Still to give</span><strong>{<Money value={due.required - due.collected} />}</strong></div></section><LedgerBreakdown required={due.required} collected={due.collected} verified={due.verified} /></> : <><section className="metric-grid compact"><Metric icon={IndianRupee} label="Required total" value={<Money value={item.requiredTotal} />} /><Metric icon={IndianRupee} label="Collected" value={<Money value={item.collected} />} tone="amber" /><Metric icon={BadgeCheck} label="Verified" value={<Money value={item.verified} />} tone="green" /><Metric icon={Clock3} label="Awaiting" value={<Money value={item.collected - item.verified} />} tone="blue" /></section><SectionHeading title="Taluk progress" />{item.talukProgress.length ? <div className="taluk-progress">{item.talukProgress.map(progress => { const percent = progress.required ? progress.collected / progress.required * 100 : 0; return <div key={progress.id}><div><strong>{progress.name}</strong><span>{Math.round(percent)}% collected</span></div><Progress value={percent} /></div> })}</div> : <p className="subtle">No obligations were created for this case.</p>}{admin && <CaseWhatsAppList item={item} />}</>}</div>
}

function CaseWhatsAppList({ item }: { item: CaseRecord }) {
  const { members, caseWhatsAppTracking } = useAppData()
  const [query, setQuery] = useState('')
  const [statuses, setStatuses] = useState<Record<string, CaseWhatsAppTracking['status']>>({})
  const [updating, setUpdating] = useState<string[]>([])
  const [error, setError] = useState('')
  const affected = members.filter(member => member.obligations?.some(obligation => obligation.caseId === item.id))
  useEffect(() => {
    setStatuses(Object.fromEntries(caseWhatsAppTracking
      .filter(entry => entry.caseId === item.id)
      .map(entry => [entry.memberId, entry.status])))
  }, [caseWhatsAppTracking, item.id])
  const term = query.trim().toLowerCase()
  const visible = affected.filter(member => !term
    || member.name.toLowerCase().includes(term)
    || member.code.toLowerCase().includes(term)
    || member.taluk.toLowerCase().includes(term))
  const messageFor = (member: MemberRecord) => [
    'കാരുണ്യസ്പർശം',
    '',
    `നമസ്കാരം ${member.name},`,
    '',
    `കാരുണ്യസ്പർശം അംഗമായ ${item.name}യുടെ നിര്യാണത്തെ തുടർന്ന് പുതിയ സഹായ സംഭാവന അഭ്യർത്ഥന ആരംഭിച്ചിരിക്കുന്നു.`,
    '',
    `കേസ് നമ്പർ: ${item.caseNumber}`,
    `നിര്യാണ തീയതി: ${item.deathDate}`,
    `താങ്കളുടെ വിഹിതം: ${formatAmount(item.amount)} രൂപ`,
    '',
    'ദയവായി തുക താങ്കൾക്ക് നിയോഗിച്ചിട്ടുള്ള കളക്ഷൻ ഏജന്റിന് കൈമാറുക.',
    '',
    'കൂടുതൽ വിവരങ്ങൾ:',
    `${window.location.origin}/member/cases/${item.id}`,
    '',
    'നന്ദി,',
    'കാരുണ്യസ്പർശം',
  ].join('\n')
  const statusFor = (memberId: string) => statuses[memberId] || 'NOT_SENT'
  const saveStatus = async (memberId: string, status: CaseWhatsAppTracking['status']) => {
    const previous = statusFor(memberId)
    setError('')
    setStatuses(current => ({ ...current, [memberId]: status }))
    setUpdating(current => [...current, memberId])
    try {
      const saved = await workspaceApi.updateCaseWhatsAppStatus(item.id, memberId, status)
      setStatuses(current => ({ ...current, [memberId]: saved.status }))
    } catch (reason) {
      setStatuses(current => ({ ...current, [memberId]: previous }))
      setError(reason instanceof ApiError ? reason.message : 'Could not update the WhatsApp status.')
    } finally {
      setUpdating(current => current.filter(id => id !== memberId))
    }
  }
  const recordOpened = (memberId: string) => {
    if (statusFor(memberId) === 'NOT_SENT') void saveStatus(memberId, 'OPENED')
  }
  const counts = affected.reduce((result, member) => {
    const status = statusFor(member.id)
    result[status] += 1
    if (!whatsappLink(member.phone, 'Message')) result.noNumber += 1
    return result
  }, { SENT: 0, OPENED: 0, NOT_SENT: 0, noNumber: 0 })

  return <section className="case-whatsapp-panel">
    <SectionHeading title={`Notify members on WhatsApp (${affected.length})`} />
    {affected.length ? <>
      <div className="whatsapp-summary" aria-label="WhatsApp notification summary">
        <div><span>Sent</span><strong>{counts.SENT}</strong></div>
        <div><span>WhatsApp opened</span><strong>{counts.OPENED}</strong></div>
        <div><span>Not sent</span><strong>{counts.NOT_SENT}</strong></div>
        <div><span>No number</span><strong>{counts.noNumber}</strong></div>
      </div>
      <SearchBox value={query} onChange={setQuery} placeholder="Search member name, code, or taluk" />
      {error && <p className="form-error">{error}</p>}
      <div className="selected-items case-whatsapp-list">
        {visible.map(member => {
          const href = whatsappLink(member.phone, messageFor(member))
          const status = statusFor(member.id)
          const busy = updating.includes(member.id)
          return <div key={member.id}>
            <span>{member.name}<small>{member.code} · {member.taluk}</small></span>
            <div className="case-whatsapp-actions">
              <span className={`whatsapp-tracking-status ${status.toLowerCase().replace('_', '-')}`}>
                {status === 'SENT' ? 'Sent' : status === 'OPENED' ? 'Opened' : 'Not sent'}
              </span>
              {href ? <>
                <a className="small-action whatsapp-action" href={href} target="_blank" rel="noreferrer" onClick={() => recordOpened(member.id)} aria-label={`Open WhatsApp message for ${member.name}`}><FaWhatsapp />WhatsApp</a>
                <button className="small-action tracking-action" disabled={busy} onClick={() => void saveStatus(member.id, status === 'SENT' ? 'NOT_SENT' : 'SENT')} aria-label={status === 'SENT' ? `Undo sent status for ${member.name}` : `Mark WhatsApp message sent to ${member.name}`}>
                  {status === 'SENT' ? <><X />Undo</> : <><Check />Mark sent</>}
                </button>
              </> : <span className="whatsapp-unavailable">No WhatsApp number</span>}
            </div>
          </div>
        })}
      </div>
      {!visible.length && <p className="subtle">No members match this search.</p>}
    </> : <p className="subtle">No affected members were found for this case.</p>}
  </section>
}

function MemberDues() {
  const { memberDues } = useAppData()
  const [filter, setFilter] = useState<'Outstanding' | 'All'>('Outstanding')
  const open = memberDues.filter(d => d.required - d.collected > 0)
  const visible = filter === 'Outstanding' ? open : memberDues
  return <div className="page-stack"><section className="due-total"><div><span>Outstanding amount</span><strong>{<Money value={open.reduce((s, d) => s + d.required - d.collected, 0)} />}</strong></div><IndianRupee /></section><div className="filter-row"><button className={`chip ${filter === 'Outstanding' ? 'active' : ''}`} onClick={() => setFilter('Outstanding')}>Outstanding ({open.length})</button><button className={`chip ${filter === 'All' ? 'active' : ''}`} onClick={() => setFilter('All')}>All obligations ({memberDues.length})</button></div>{visible.length ? <div className="dues-list">{visible.map(d => <article key={d.caseId}><div className="item-top"><div><span>{d.caseNumber}</span><h3>{d.name}</h3></div><Status value={getMoneyStatus(d.required, d.collected, d.verified)} /></div><LedgerBreakdown required={d.required} collected={d.collected} verified={d.verified} /></article>)}</div> : <div className="empty-review"><BadgeCheck /><h3>No outstanding obligations</h3><p>Completed obligations remain available under All obligations.</p></div>}</div>
}

function MemberPayments({ collections }: { collections: CollectionRecord[] }) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'All' | 'Awaiting' | 'Verified'>('All')
  const mine = collections.filter(item => {
    const awaiting = item.status !== 'Verified'
    const matchesStatus = filter === 'All' || (filter === 'Awaiting' ? awaiting : !awaiting)
    const term = query.trim().toLowerCase()
    return matchesStatus && (!term || item.label.toLowerCase().includes(term) || item.receipt.toLowerCase().includes(term) || String(item.collectorName || '').toLowerCase().includes(term))
  })
  return <div className="page-stack"><SearchBox value={query} onChange={setQuery} placeholder="Search payments" /><div className="filter-row">{(['All', 'Awaiting', 'Verified'] as const).map(status => <button key={status} className={`chip ${filter === status ? 'active' : ''}`} onClick={() => setFilter(status)}>{status}</button>)}</div>{mine.length ? <div className="payment-list">{mine.map(c => <article key={c.id}><div className={`payment-icon ${c.status.toLowerCase()}`}>{c.status === 'Verified' ? <Check /> : <Clock3 />}</div><div><strong>{c.label}</strong><span>{c.receipt} · {c.date}</span><small>{c.method} · Collected by {c.collectorName}</small></div><div><strong>{<Money value={c.amount} />}</strong><Status value={c.status === 'Batched' || c.status === 'Recorded' ? 'Awaiting Verification' : 'Verified'} /></div></article>)}</div> : <div className="empty-review"><Receipt /><h3>No payments found</h3><p>Try another search or status filter.</p></div>}</div>
}

function PermanentMembershipDetails({ member }: { member: MemberRecord }) {
  const verified = member.permanentVerified || 0, collected = member.permanentCollected || 0
  const target = member.permanentTarget || 0, remaining = Math.max(target - verified, 0)
  return <><section className="permanent-hero"><div className="permanent-seal"><ShieldCheck /></div><span>Verified progress</span><strong>{<Money value={verified} />}</strong><p>of {<Money value={target} />} target</p><Progress value={target ? verified / target * 100 : 0} /><small>{<Money value={remaining} />} remaining</small></section><section className="metric-grid compact"><Metric icon={IndianRupee} label="Collected" value={<Money value={collected} />} tone="blue" /><Metric icon={Clock3} label="Awaiting verification" value={<Money value={Math.max(collected - verified, 0)} />} tone="amber" /><Metric icon={ShieldCheck} label="Membership" value={member.membership || 'Regular'} /></section><p className="subtle">{collected ? <><Money value={collected} /> has been recorded toward permanent membership.</> : 'No permanent-membership instalments have been recorded.'}</p></>
}

function AgentCollections({ online, collections, setCollections: _setCollections, notify, reload }: { online: boolean; collections: CollectionRecord[]; setCollections: (c: CollectionRecord[]) => void; notify: (message: string) => void; reload: () => Promise<void> }) {
  const [modal, setModal] = useState(false)
  const [selectedMemberId, setSelectedMemberId] = useState<string | undefined>()
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'Pending' | 'Partial'>('Pending')
  const { members } = useAppData()
  const outstandingFor = (member: MemberRecord) => member.pending + Math.max(
    (member.permanentAccountId ? member.permanentTarget || 0 : 0) - (member.permanentCollected || 0), 0
  )
  const visible = members.filter(member => {
    const outstanding = outstandingFor(member)
    const hasPartialDeathPayment = member.obligations?.some(obligation => obligation.available > 0
      && collections.some(item => item.memberId === member.id && item.caseId === obligation.caseId)) || false
    const permanentOutstanding = Math.max(
      (member.permanentAccountId ? member.permanentTarget || 0 : 0) - (member.permanentCollected || 0), 0
    )
    const hasPartialPermanentPayment = permanentOutstanding > 0 && (member.permanentCollected || 0) > 0
    const hasPartialPayment = hasPartialDeathPayment || hasPartialPermanentPayment
    const matchesStatus = outstanding > 0 && (filter === 'Partial' ? hasPartialPayment : !hasPartialPayment)
    return member.status === 'Active' && matchesStatus && (member.name.toLowerCase().includes(query.toLowerCase()) || member.code.toLowerCase().includes(query.toLowerCase()))
  })
  const record = async (memberId: string, type: string, amount: number, method: CollectionRecord['method']) => {
    const member = members.find(item => item.id === memberId); if (!member) return
    const isPermanent = type === 'permanent'; const obligation = member.obligations?.find(item => item.caseId === type)
    await workspaceApi.recordCollection({
      client_request_id: crypto.randomUUID(), member_id: memberId,
      collection_type: isPermanent ? 'PERMANENT_MEMBERSHIP' : 'DEATH_CONTRIBUTION',
      case_obligation_id: isPermanent ? null : obligation?.id,
      permanent_account_id: isPermanent ? member.permanentAccountId : null,
      amount, method: method.toUpperCase().replaceAll(' ', '_'), collected_at: new Date().toISOString()
    })
    await reload(); setModal(false); notify(`${formatMoney(amount)} collection recorded for ${member.name}.`)
  }
  return <div className="page-stack"><section className="collection-banner"><div><span>Collected, not handed over</span><strong>{<Money value={collections.filter(c => c.status === 'Recorded').reduce((s, c) => s + c.amount, 0)} />}</strong></div><button className="secondary" onClick={() => location.assign('/agent/handovers')}>Prepare handover <ArrowRight /></button></section><div className="toolbar"><SearchBox value={query} onChange={setQuery} placeholder="Search outstanding payments" /><button className="primary" disabled={!online} onClick={() => { setSelectedMemberId(undefined); setModal(true) }}><IndianRupee /> Record payment</button></div><div className="filter-row">{(['Pending', 'Partial'] as const).map(status => <button key={status} className={`chip ${filter === status ? 'active' : ''}`} onClick={() => setFilter(status)}>{status}</button>)}</div>{visible.length ? <div className="member-list">{visible.map(m => <MemberRow member={m} key={m.id} pending={outstandingFor(m)} action={() => { setSelectedMemberId(m.id); setModal(true) }} actionLabel="Record payment" />)}</div> : <div className="empty-review"><BadgeCheck /><h3>No outstanding payments found</h3><p>Try another search or check the other payment status.</p></div>}{modal && <CollectionModal initialMemberId={selectedMemberId} onClose={() => { setModal(false); setSelectedMemberId(undefined) }} onRecord={record} />}</div>
}

function AgentDeposits({ online, collections, setCollections: _setCollections, deposits, setDeposits: _setDeposits, notify, reload, session }: { online: boolean; collections: CollectionRecord[]; setCollections: (c: CollectionRecord[]) => void; deposits: DepositRecord[]; setDeposits: (d: DepositRecord[]) => void; notify: (message: string) => void; reload: () => Promise<void>; session: Session }) {
  const [modal, setModal] = useState(false)
  const [filter, setFilter] = useState<'All' | DepositRecord['status']>('All')
  const [adminNotice, setAdminNotice] = useState<{ number: string; amount: number; note: string; submitted: string; href: string } | null>(null)
  const own = deposits.filter(item => item.agent === session.name && (filter === 'All' || item.status === filter))
  const prepareAdminNotice = (batch: Record<string, any>, entryCount: number) => {
    const number = String(batch.deposit_number || batch.number || '')
    const amount = Number(batch.calculated_total ?? batch.calculated ?? 0)
    const note = String(batch.agent_message || batch.handover_note || 'നൽകിയിട്ടില്ല')
    const submittedAt = String(batch.submitted_at || new Date().toISOString())
    const submitted = dateTimeText(submittedAt)
    const submittedForMessage = new Intl.DateTimeFormat('ml-IN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(submittedAt))
    const message = [
      'കാരുണ്യസ്പർശം',
      '',
      'അഡ്മിൻ പരിശോധനയ്ക്കായി ഒരു പുതിയ കളക്ഷൻ കൈമാറ്റം സമർപ്പിച്ചിരിക്കുന്നു.',
      '',
      `കൈമാറ്റ നമ്പർ: ${number}`,
      `കളക്ഷൻ ഏജന്റ്: ${session.name}`,
      `താലൂക്ക്: ${session.talukName || 'അസൈൻ ചെയ്ത താലൂക്ക്'}`,
      `കൈമാറിയ തുക: ${formatAmount(amount)} രൂപ`,
      `കളക്ഷൻ എൻട്രികളുടെ എണ്ണം: ${entryCount}`,
      `കുറിപ്പ്: ${note}`,
      `സമർപ്പിച്ച സമയം: ${submittedForMessage}`,
      '',
      'കൈമാറ്റം പരിശോധിക്കാൻ:',
      `${window.location.origin}/admin/handovers`,
      '',
      'കാരുണ്യസ്പർശം',
    ].join('\n')
    setAdminNotice({ number, amount, note, submitted, href: whatsappLink(ADMIN_WHATSAPP_NUMBER, message) })
  }
  const create = async (ids: string[], amount: number, note: string) => {
    const batch = await workspaceApi.createHandover({ collection_ids: ids, declared_deposit_amount: amount, deposited_at: new Date().toISOString(), agent_message: note || null })
    const submitted = await workspaceApi.submitHandover(String(batch.id), Number(batch.version || 1))
    await reload(); setModal(false); prepareAdminNotice(submitted, ids.length); notify('Handover submitted for administrator confirmation.')
  }
  const submitDraft = async (deposit: DepositRecord) => {
    try { const submitted = await workspaceApi.submitHandover(deposit.id, deposit.version || 1); await reload(); prepareAdminNotice(submitted, deposit.collectionIds.length); notify('Draft handover submitted for administrator confirmation.') }
    catch (cause) { notify(cause instanceof Error ? cause.message : 'Draft handover could not be submitted.') }
  }
  const statusLabel = (status: 'All' | DepositRecord['status']) => status === 'Submitted' ? 'Awaiting receipt' : status === 'Approved' ? 'Received' : status
  return <div className="page-stack"><div className="toolbar"><div><h2 className="mobile-section-title">Collection handovers</h2><p className="subtle">Submit collected amounts to the administrator.</p></div><button className="primary" disabled={!online || !collections.some(c => c.status === 'Recorded')} onClick={() => setModal(true)}><Plus /> New handover</button></div><div className="filter-row">{(['All', 'Draft', 'Submitted', 'Approved', 'Rejected'] as const).map(status => <button key={status} className={`chip ${filter === status ? 'active' : ''}`} onClick={() => setFilter(status)}>{statusLabel(status)}</button>)}</div>{own.length ? <div className="list-surface deposits-full">{own.map(d => <DepositRow key={d.id} deposit={d} action={d.status === 'Draft' && online ? () => submitDraft(d) : undefined} actionLabel="Submit" />)}</div> : <div className="empty-review"><WalletCards /><h3>No handovers found</h3><p>Create a handover from recorded collections or choose another status.</p></div>}{modal && <DepositModal collections={collections.filter(c => c.status === 'Recorded')} onClose={() => setModal(false)} onSubmit={create} />}{adminNotice && <DepositAdminNotice notice={adminNotice} onClose={() => setAdminNotice(null)} />}</div>
}

function AdminDeposits({ deposits, setDeposits: _setDeposits, collections, setCollections: _setCollections, online, notify, reload }: { deposits: DepositRecord[]; setDeposits: (d: DepositRecord[]) => void; collections: CollectionRecord[]; setCollections: (c: CollectionRecord[]) => void; online: boolean; notify: (message: string, tone?: Toast['tone']) => void; reload: () => Promise<void> }) {
  const { members } = useAppData()
  const [selected, setSelected] = useState<DepositRecord | null>(null)
  const [filter, setFilter] = useState<'Submitted' | 'Approved' | 'Rejected'>('Submitted')
  const [reviewing, setReviewing] = useState(false)
  const [recording, setRecording] = useState(false)
  const filteredDeposits = deposits.filter(deposit => deposit.status === filter)
  const selectedCollections = useMemo(
    () => selected ? collections.filter(collection => selected.collectionIds.includes(collection.id)) : [],
    [collections, selected],
  )
  const memberNotifications = useMemo(() => {
    const grouped = new Map<string, { id: string; name: string; phone: string; amount: number; labels: string[] }>()
    selectedCollections.forEach(collection => {
      const member = members.find(item => item.id === collection.memberId)
      const existing = grouped.get(collection.memberId)
      if (existing) {
        existing.amount += collection.amount
        if (!existing.labels.includes(collection.label)) existing.labels.push(collection.label)
      } else {
        grouped.set(collection.memberId, {
          id: collection.memberId,
          name: member?.name || collection.member,
          phone: member?.phone || '',
          amount: collection.amount,
          labels: [collection.label],
        })
      }
    })
    return [...grouped.values()]
  }, [members, selectedCollections])
  const messageFor = (member: (typeof memberNotifications)[number]) => [
    'കാരുണ്യസ്പർശം',
    '',
    `നമസ്കാരം ${member.name},`,
    '',
    `താങ്കളിൽ നിന്ന് സ്വീകരിച്ച ${formatAmount(member.amount)} രൂപയുടെ പേയ്‌മെന്റ് അഡ്മിൻ സ്വീകരിച്ച് സ്ഥിരീകരിച്ചിരിക്കുന്നു.`,
    '',
    `കൈമാറ്റ നമ്പർ: ${selected?.number || ''}`,
    '',
    'നന്ദി,',
    'കാരുണ്യസ്പർശം',
  ].join('\n')
  const filterCopy = filter === 'Submitted'
    ? { title: 'No handovers awaiting receipt', detail: 'An agent must submit a collection handover before it can be confirmed or rejected.' }
    : { title: `No ${filter === 'Approved' ? 'received' : filter.toLowerCase()} handovers`, detail: `Handovers marked ${filter === 'Approved' ? 'received' : filter.toLowerCase()} will appear here.` }
  const agentMessageFor = (deposit: DepositRecord) => {
    const approved = deposit.status === 'Approved'
    return [
      'കാരുണ്യസ്പർശം',
      '',
      `നമസ്കാരം ${deposit.agent},`,
      '',
      approved
        ? 'താങ്കൾ സമർപ്പിച്ച കളക്ഷൻ കൈമാറ്റം അഡ്മിൻ സ്വീകരിച്ച് സ്ഥിരീകരിച്ചിരിക്കുന്നു.'
        : 'താങ്കൾ സമർപ്പിച്ച കളക്ഷൻ കൈമാറ്റം അഡ്മിൻ നിരസിച്ചിരിക്കുന്നു.',
      '',
      `കൈമാറ്റ നമ്പർ: ${deposit.number}`,
      `തുക: ${formatAmount(deposit.calculated)} രൂപ`,
      `സ്ഥിതി: ${approved ? 'സ്വീകരിച്ച് സ്ഥിരീകരിച്ചു' : 'നിരസിച്ചു'}`,
      ...(approved
        ? ['', 'ഈ കൈമാറ്റത്തിലെ കളക്ഷനുകൾ സ്ഥിരീകരിച്ചിരിക്കുന്നു.']
        : [
            `നിരസിക്കാനുള്ള കാരണം: ${deposit.rejectionReason || 'നൽകിയിട്ടില്ല'}`,
            '',
            'ദയവായി കാരണം പരിശോധിച്ച് ആവശ്യമായ തിരുത്തലുകൾ നടത്തിയ ശേഷം കളക്ഷൻ എൻട്രികൾ പുതിയ കൈമാറ്റമായി വീണ്ടും സമർപ്പിക്കുക.',
          ]),
      '',
      'കൂടുതൽ വിവരങ്ങൾ:',
      `${window.location.origin}/agent/handovers`,
      '',
      'നന്ദി,',
      'കാരുണ്യസ്പർശം',
    ].join('\n')
  }
  const agentMessageHref = selected && selected.status !== 'Submitted'
    ? whatsappLink(selected.agentPhone, agentMessageFor(selected))
    : ''
  const selectFilter = (status: 'Submitted' | 'Approved' | 'Rejected') => {
    setFilter(status)
    setSelected(null)
  }
  const review = async (decision: 'Approved' | 'Rejected') => {
    if (!selected || selected.status !== 'Submitted' || reviewing) return
    const reason = decision === 'Rejected' ? window.prompt('Enter the rejection reason:')?.trim() : undefined
    if (decision === 'Rejected' && (!reason || reason.length < 3)) return
    setReviewing(true)
    try {
      await workspaceApi.reviewHandover(selected.id, selected.version || 1, decision === 'Approved', reason)
      const reviewedDeposit: DepositRecord = {
        ...selected,
        status: decision,
        rejectionReason: decision === 'Rejected' ? reason : selected.rejectionReason,
        version: (selected.version || 1) + 1,
      }
      await reload()
      setFilter(decision)
      setSelected(reviewedDeposit)
      notify(decision === 'Approved' ? 'Handover received. WhatsApp messages are ready for the agent and members.' : 'Handover rejected. The agent WhatsApp message is ready.', decision === 'Rejected' ? 'danger' : 'success')
    } catch (error) {
      notify(error instanceof Error ? error.message : `Unable to ${decision.toLowerCase()} the handover.`, 'danger')
    } finally {
      setReviewing(false)
    }
  }
  return <div className="page-stack">
    <div className="toolbar collection-admin-toolbar"><div><h2 className="mobile-section-title">Collections</h2><p className="subtle">Record money received from a taluk agent and verify member balances.</p></div><button className="primary" disabled={!online} onClick={() => setRecording(true)}><Plus /> Record collection batch</button></div>
    <div className="filter-row">
      <button className={`chip ${filter === 'Submitted' ? 'active' : ''}`} onClick={() => selectFilter('Submitted')}>Pending ({deposits.filter(d => d.status === 'Submitted').length})</button>
      <button className={`chip ${filter === 'Approved' ? 'active' : ''}`} onClick={() => selectFilter('Approved')}>Received ({deposits.filter(d => d.status === 'Approved').length})</button>
      <button className={`chip ${filter === 'Rejected' ? 'active' : ''}`} onClick={() => selectFilter('Rejected')}>Rejected ({deposits.filter(d => d.status === 'Rejected').length})</button>
    </div>
    <div className="review-layout">
      <div className="list-surface">
        {filteredDeposits.length
          ? filteredDeposits.map(d => <DepositRow key={d.id} deposit={d} admin onClick={() => setSelected(d)} selected={selected?.id === d.id} />)
          : <div className="empty-review"><FileCheck2 /><h3>{filterCopy.title}</h3><p>{filterCopy.detail}</p></div>}
      </div>
      <section className="review-detail">
        {selected ? <>
          <div className="review-head"><div><span className="case-number">{selected.number}</span><h2>{selected.agent}</h2><p>{selected.taluk} · {selected.submitted}</p></div><HandoverStatus value={selected.status} /></div>
          <div className="amount-match"><div><span>Collection total</span><strong>{<Money value={selected.calculated} />}</strong></div><div><span>Amount handed over</span><strong>{<Money value={selected.declared} />}</strong></div><p className={selected.calculated === selected.declared ? 'match' : 'mismatch'}>{selected.calculated === selected.declared ? <CheckCircle2 /> : <AlertCircle />}{selected.calculated === selected.declared ? 'Amounts match exactly' : 'Confirmation blocked: total mismatch'}</p></div>
          <dl className="review-data"><div><dt>Agent</dt><dd>{selected.agent}</dd></div><div><dt>Taluk</dt><dd>{selected.taluk}</dd></div><div><dt>Handover note</dt><dd>{selected.note || 'Not provided'}</dd></div></dl>
          <SectionHeading title="Collection entries" />
          <div className="selected-items">
            {selected.collectionIds.length ? (selected.status === 'Approved'
              ? memberNotifications.map(member => {
                const href = whatsappLink(member.phone, messageFor(member))
                return <div key={member.id}>
                  <span>{member.name}<small>{member.labels.join(', ')}</small></span>
                  <div className="selected-item-actions">
                    <strong>{<Money value={member.amount} />}</strong>
                    {href
                      ? <a className="small-action whatsapp-action" href={href} target="_blank" rel="noreferrer" aria-label={`Send WhatsApp message to ${member.name}`}><FaWhatsapp />WhatsApp</a>
                      : <span className="whatsapp-unavailable">No WhatsApp number</span>}
                  </div>
                </div>
              })
              : selectedCollections.map(collection => <div key={collection.id}><span>{collection.member}<small>{collection.label}</small></span><strong>{<Money value={collection.amount} />}</strong></div>))
              : <div><span>Multiple verified entries<small>Item breakdown retained in batch</small></span><strong>{<Money value={selected.calculated} />}</strong></div>}
          </div>
          {selected.status !== 'Submitted' && <div className="agent-review-message">
            <div><FaWhatsapp /><span><strong>Notify {selected.agent}</strong><small>{selected.status === 'Approved' ? 'Send the receipt confirmation to the agent.' : 'Send the rejection reason and corrective action to the agent.'}</small></span></div>
            {agentMessageHref
              ? <a className="primary admin-whatsapp-action" href={agentMessageHref} target="_blank" rel="noreferrer"><FaWhatsapp /> WhatsApp agent</a>
              : <span className="whatsapp-unavailable">Agent WhatsApp number unavailable</span>}
          </div>}
          {selected.status === 'Submitted' && <div className="review-actions"><button className="danger-btn" disabled={!online || reviewing} onClick={() => review('Rejected')}><XCircle /> {reviewing ? 'Working...' : 'Reject'}</button><button className="primary" disabled={!online || reviewing || selected.calculated !== selected.declared} onClick={() => review('Approved')}><CheckCircle2 /> {reviewing ? 'Working...' : 'Confirm receipt'}</button></div>}
        </> : <div className="empty-review"><FileCheck2 /><h3>{filteredDeposits.length ? `Select a ${filter === 'Approved' ? 'received' : filter.toLowerCase()} handover` : filterCopy.title}</h3><p>{filteredDeposits.length ? (filter === 'Submitted' ? 'Review the collection total, handed-over amount, note, and entries before deciding.' : 'Select a handover from the list to view its details.') : filterCopy.detail}</p></div>}
      </section>
    </div>
    {recording && <AdminCollectionBatchModal onClose={() => setRecording(false)} onRecorded={async amount => { setRecording(false); setFilter('Approved'); setSelected(null); await reload(); notify(`${formatMoney(amount)} recorded and verified.`) }} />}
  </div>
}

function MembersPage({ role, reload, notify }: { role: 'agent' | 'admin'; reload?: () => Promise<void>; notify?: (message: string, tone?: Toast['tone']) => void }) {
  const navigate = useNavigate(); const [query, setQuery] = useState(''), [adding, setAdding] = useState(false)
  const [filter, setFilter] = useState<'Active' | 'Permanent' | 'Inactive'>('Active')
  const [talukFilter, setTalukFilter] = useState('All')
  const [editing, setEditing] = useState<MemberRecord | null>(null)
  const { members, cases } = useAppData()
  const talukOptions = useMemo(() => [...new Set(members.map(member => member.taluk).filter(Boolean))].sort((a, b) => a.localeCompare(b)), [members])
  const talukMembers = talukFilter === 'All' ? members : members.filter(member => member.taluk === talukFilter)
  const visible = talukMembers.filter(member => {
    const matchesFilter = filter === 'Permanent' ? member.membership === 'Permanent' : filter === 'Inactive' ? member.status !== 'Active' : member.status === 'Active'
    const term = query.toLowerCase()
    return matchesFilter && (member.name.toLowerCase().includes(term) || member.code.toLowerCase().includes(term) || (member.ardNo || '').toLowerCase().includes(term) || member.phone.toLowerCase().includes(term))
  })
  const counts = { Active: talukMembers.filter(item => item.status === 'Active').length, Permanent: talukMembers.filter(item => item.membership === 'Permanent').length, Inactive: talukMembers.filter(item => item.status !== 'Active').length }
  const talukCaseRows = talukFilter === 'All'
    ? cases.map(item => ({ id: item.id, required: item.requiredTotal, collected: item.collected }))
    : cases.flatMap(item => item.talukProgress
      .filter(progress => progress.name === talukFilter)
      .map(progress => ({ id: item.id, required: progress.required, collected: progress.collected })))
  const talukSummary = {
    cases: talukCaseRows.length,
    collected: talukCaseRows.reduce((sum, item) => sum + item.collected, 0),
    pending: talukCaseRows.reduce((sum, item) => sum + Math.max(item.required - item.collected, 0), 0),
  }
  return <div className="page-stack"><div className="toolbar member-toolbar"><SearchBox value={query} onChange={setQuery} placeholder="Search name, member code, ARD or phone" />{role === 'admin' && <label className="taluk-filter"><select aria-label="Filter members by taluk" value={talukFilter} onChange={event => setTalukFilter(event.target.value)}><option value="All">All taluks</option>{talukOptions.map(taluk => <option value={taluk} key={taluk}>{taluk}</option>)}</select></label>}{role === 'admin' && <button className="primary" onClick={() => setAdding(true)}><Plus /> Add member</button>}</div>{role === 'admin' && <section className="taluk-summary" aria-label={`${talukFilter === 'All' ? 'All taluks' : talukFilter} financial summary`}><div><HeartHandshake /><span>Death cases</span><strong>{talukSummary.cases}</strong></div><div><BadgeCheck /><span>Collected</span><strong><Money value={talukSummary.collected} /></strong></div><div><Clock3 /><span>Pending</span><strong><Money value={talukSummary.pending} /></strong></div></section>}<div className="filter-row">{(['Active', 'Permanent', 'Inactive'] as const).map(status => <button key={status} className={`chip ${filter === status ? 'active' : ''}`} onClick={() => setFilter(status)}>{status} ({counts[status]})</button>)}</div>{visible.length ? <div className="member-list">{visible.map(m => <MemberRow member={m} key={m.id} action={role === 'admin' ? () => setEditing(m) : undefined} actionLabel="Edit" onClick={role === 'agent' ? () => navigate(`/agent/members/${m.id}`) : undefined} />)}</div> : <div className="empty-review"><Users /><h3>No members found</h3><p>Try another search, taluk, or member status.</p></div>}{adding && reload && notify && <InitialSetupModal kind="member" onClose={() => setAdding(false)} reload={reload} notify={notify} />}{editing && reload && notify && <EditMemberModal member={editing} onClose={() => setEditing(null)} reload={reload} notify={notify} />}</div>
}

function MemberDetail({ id, collections }: { id: string; collections: CollectionRecord[] }) {
  const { members } = useAppData()
  const m = members.find(x => x.id === id)
  if (!m) return <div className="empty-review"><Users /><h3>Member not found</h3></div>
  const target = m.permanentTarget || 0
  const collected = m.permanentCollected || 0
  const awaiting = Math.max(collected - m.permanentVerified, 0)
  const stillToCollect = Math.max(target - collected, 0)
  const payments = collections.filter(item => item.memberId === id)
  return <div className="page-stack detail-page"><button className="back-link" onClick={() => history.back()}><ArrowLeft /> Back to members</button><section className="profile-hero"><Avatar name={m.name} color="#276749" large /><div><span>{m.code}</span><h2>{m.name}</h2><p>{m.phone} · {m.taluk} Taluk</p><Status value={m.membership} /></div></section><section className="metric-grid compact"><Metric icon={IndianRupee} label="Death-case dues" value={<Money value={m.pending} />} tone="red" /><Metric icon={IndianRupee} label="Permanent collected" value={<Money value={collected} />} tone="amber" /><Metric icon={Clock3} label="Awaiting verification" value={<Money value={awaiting} />} tone="blue" /><Metric icon={ShieldCheck} label="Permanent verified" value={<Money value={m.permanentVerified} />} tone="green" /></section><SectionHeading title="Permanent membership" /><section className="progress-section"><div className="progress-copy"><div><span>Collected</span><strong>{<Money value={collected} />}</strong></div><div><span>Verified</span><strong>{<Money value={m.permanentVerified} />}</strong></div></div><Progress value={target ? (m.permanentVerified / target) * 100 : 0} /><p><Clock3 /> {<Money value={awaiting} />} awaiting verification · {<Money value={stillToCollect} />} still to collect</p></section><SectionHeading title="Payment history" />{payments.length ? <div className="payment-list">{payments.map(payment => <article key={payment.id}><div className={`payment-icon ${payment.status.toLowerCase()}`}>{payment.status === 'Verified' ? <Check /> : <Clock3 />}</div><div><strong>{payment.label}</strong><span>{payment.receipt} · {payment.date}</span><small>{payment.method}</small></div><div><strong>{<Money value={payment.amount} />}</strong><Status value={payment.status === 'Recorded' || payment.status === 'Batched' ? 'Awaiting Verification' : 'Verified'} /></div></article>)}</div> : <p className="subtle">No payments have been recorded for this member.</p>}</div>
}

function NotificationsPage() {
  const { notifications } = useAppData(); const unread = notifications.filter(item => item.unread).length
  const [filter, setFilter] = useState<'All' | 'Unread'>('All')
  const visible = filter === 'Unread' ? notifications.filter(item => item.unread) : notifications
  return <div className="page-stack"><div className="filter-row"><button className={`chip ${filter === 'All' ? 'active' : ''}`} onClick={() => setFilter('All')}>All ({notifications.length})</button><button className={`chip ${filter === 'Unread' ? 'active' : ''}`} onClick={() => setFilter('Unread')}>Unread ({unread})</button></div>{visible.length ? <div className="notification-list">{visible.map(item => <article className={item.unread ? 'unread' : ''} key={item.id}><div className={`notice-icon ${item.kind}`}>{item.kind === 'verified' ? <BadgeCheck /> : <HeartHandshake />}</div><div><div><strong>{item.title}</strong>{item.unread && <i />}</div><p>{item.body}</p><span>{item.time}</span></div></article>)}</div> : <div className="empty-review"><Bell /><h3>{filter === 'Unread' ? 'No unread notifications' : 'No notifications'}</h3><p>New case and payment updates will appear here.</p></div>}</div>
}

function AccountPage({ session, notify }: { session: Session; notify: (message: string, tone?: Toast['tone']) => void }) {
  const role = session.role, p = session
  const { members } = useAppData()
  const member = role === 'member' ? members[0] : undefined
  const [changingPassword, setChangingPassword] = useState(false)
  const subtitle = role === 'member' ? [p.memberCode, p.talukName && `${p.talukName} Taluk`].filter(Boolean).join(' · ') : role === 'agent' ? ['Collection agent', p.talukName && `${p.talukName} Taluk`].filter(Boolean).join(' · ') : 'System administrator'
  return <div className="page-stack"><section className="account-head"><div className="avatar xl">{initials(p.name)}</div><h2>{p.name}</h2><p>{subtitle}</p><Status value="Active" /></section>{member && <><SectionHeading title="Permanent membership progress" /><PermanentMembershipDetails member={member} /></>}<section className="settings-list"><button onClick={() => setChangingPassword(true)}><LockKeyhole /><span><strong>Change password</strong><small>Update your account password</small></span><ChevronRight /></button></section><div className="profile-data"><span>Full name</span><strong>{p.name}</strong><span>Login ID</span><strong>{p.loginId}</strong><span>Role</span><strong>{role[0].toUpperCase() + role.slice(1)}</strong>{p.talukName && <><span>Taluk</span><strong>{p.talukName}</strong></>}</div>{changingPassword && <ChangePasswordModal onClose={() => setChangingPassword(false)} onChanged={() => { setChangingPassword(false); notify('Password changed successfully.') }} />}</div>
}

function ChangePasswordModal({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const [password, setPassword] = useState(''), [confirm, setConfirm] = useState('')
  const [error, setError] = useState(''), [submitting, setSubmitting] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError('')
    if (password.length < 8) { setError('Use at least 8 characters.'); return }
    if (password !== confirm) { setError('Passwords do not match.'); return }
    setSubmitting(true)
    try { await authApi.changePassword(password); onChanged() }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Password could not be changed.') }
    finally { setSubmitting(false) }
  }
  return <Modal title="Change password" onClose={onClose}><form className="modal-form" onSubmit={submit}><label>New password<input type="password" required minLength={8} autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} /></label><label>Confirm password<input type="password" required minLength={8} autoComplete="new-password" value={confirm} onChange={event => setConfirm(event.target.value)} /></label>{error && <p className="form-error"><AlertCircle />{error}</p>}<div className="modal-actions"><button className="secondary" type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={submitting}>{submitting ? 'Updating…' : 'Update password'}</button></div></form></Modal>
}

type SetupKind = 'taluk' | 'agent' | 'bank' | 'member'

function TaluksPage({ reload, notify }: { reload: () => Promise<void>; notify: (message: string, tone?: Toast['tone']) => void }) {
  const { taluks, agents, bankAccounts } = useAppData()
  const [query, setQuery] = useState('')
  const [setup, setSetup] = useState<SetupKind | null>(null)
  const [editingTaluk, setEditingTaluk] = useState<Record<string, any> | null>(null)
  const [replacingBank, setReplacingBank] = useState<Record<string, any> | null>(null)
  const [editingAgent, setEditingAgent] = useState<Record<string, any> | null>(null)
  const term = query.trim().toLowerCase()
  const visibleTaluks = taluks.filter(item => !term || String(item.name).toLowerCase().includes(term) || String(item.code).toLowerCase().includes(term) || String(item.agent_name || '').toLowerCase().includes(term))
  const visibleAgents = agents.filter(item => !term || String(item.full_name).toLowerCase().includes(term) || String(item.login_id).toLowerCase().includes(term) || String(item.taluk_name || '').toLowerCase().includes(term))
  const bankForTaluk = (taluk: Record<string, any>) => bankAccounts.find(item => String(item.taluk_id) === String(taluk.id))
  const replaceBank = (taluk: Record<string, any>) => {
    const bank = bankForTaluk(taluk)
    if (!taluk.bank_account_id && !bank) return
    setReplacingBank({
      ...taluk,
      bank_account_id: taluk.bank_account_id || bank?.id,
      agent_profile_id: taluk.agent_profile_id || bank?.agent_profile_id,
      bank_name: taluk.bank_name || bank?.bank_name,
      bank_last4: taluk.bank_last4 || bank?.last4,
      bank_branch_name: taluk.bank_branch_name || bank?.branch_name,
      bank_account_holder_name: taluk.bank_account_holder_name || bank?.account_holder_name,
      bank_ifsc_code: taluk.bank_ifsc_code || bank?.ifsc_code,
    })
  }
  const organizationReady = taluks.length > 0 && agents.length > 0
  const canAddAgent = taluks.some(item => !item.agent_name)
  const canAddBank = agents.some(agent => !taluks.find(item => String(item.id) === String(agent.taluk_id))?.bank_name)
  const steps: { kind: 'taluk' | 'agent'; title: string; detail: string; complete: boolean; enabled: boolean }[] = [
    { kind: 'taluk', title: 'Taluks', detail: `${taluks.length} configured`, complete: taluks.length > 0, enabled: true },
    { kind: 'agent', title: 'Agents', detail: `${agents.length} assigned`, complete: agents.length > 0, enabled: taluks.length > 0 },
  ]
  return <div className="page-stack">
    {!organizationReady && <section className="setup-flow">
      <div className="setup-heading"><div><span>Initial setup</span><h2>Organization setup</h2></div><small>Complete in order</small></div>
      <div className="setup-steps">{steps.map((step, index) => <article className={step.complete ? 'complete' : ''} key={step.kind}><div className="setup-number">{step.complete ? <Check /> : index + 1}</div><div><strong>{step.title}</strong><span>{step.detail}</span></div><button className="secondary" disabled={!step.enabled} onClick={() => setSetup(step.kind)}><Plus /> Add</button></article>)}</div>
    </section>}
    <div className="toolbar"><SearchBox value={query} onChange={setQuery} placeholder="Search taluk or agent" />{organizationReady && <div className="organization-actions"><button className="secondary" onClick={() => setSetup('taluk')}><Plus /> Taluk</button><button className="secondary" disabled={!canAddAgent} title={canAddAgent ? 'Add collection agent' : 'Add an unassigned taluk first'} onClick={() => setSetup('agent')}><UserRound /> Agent</button><button className="primary" disabled={!canAddBank} title={canAddBank ? 'Configure bank account' : 'Every assigned agent already has a bank'} onClick={() => setSetup('bank')}><Landmark /> Bank</button></div>}</div>
    {visibleTaluks.length ? <div className="organization-grid">{visibleTaluks.map(item => <article key={String(item.id)}><div className="org-head"><div className="org-code">{String(item.code)}</div><div className="org-actions"><button className="icon-btn" title="Edit taluk" onClick={() => setEditingTaluk(item)}><Pencil /></button><button className="icon-btn" title="Replace bank account" disabled={!item.bank_account_id && !bankForTaluk(item)} onClick={() => replaceBank(item)}><Landmark /></button></div></div><h3>{String(item.name)} Taluk</h3><dl><div><dt>Active agent</dt><dd>{String(item.agent_name || 'Not assigned')}</dd></div><div><dt>Bank account</dt><dd>{item.bank_name ? `${item.bank_name} •••• ${item.bank_last4 || ''}` : 'Not configured'}</dd></div><div><dt>Active members</dt><dd><Users />{Number(item.member_count || 0)}</dd></div></dl></article>)}</div> : <div className="empty-review"><Landmark /><h3>No taluks found</h3><p>Try another taluk code, name, or agent.</p></div>}
    <SectionHeading title="Collection agents" />
    {visibleAgents.length ? <div className="settings-list agent-admin-list">{visibleAgents.map(agent => <button key={String(agent.id)} onClick={() => setEditingAgent(agent)}><UserRound /><span><strong>{String(agent.full_name)}</strong><small>{String(agent.login_id)} · {String(agent.taluk_name || 'Unassigned')} · {titleCase(String(agent.account_status))}</small></span><Pencil /></button>)}</div> : <p className="subtle">No matching collection agents.</p>}
    {setup && <InitialSetupModal kind={setup} onClose={() => setSetup(null)} reload={reload} notify={notify} />}
    {editingTaluk && <EditTalukModal taluk={editingTaluk} onClose={() => setEditingTaluk(null)} reload={reload} notify={notify} />}
    {replacingBank && <ReplaceBankModal taluk={replacingBank} onClose={() => setReplacingBank(null)} reload={reload} notify={notify} />}
    {editingAgent && <EditAgentModal agent={editingAgent} onClose={() => setEditingAgent(null)} reload={reload} notify={notify} />}
  </div>
}

function EditAgentModal({ agent, onClose, reload, notify }: { agent: Record<string, any>; onClose: () => void; reload: () => Promise<void>; notify: (message: string, tone?: Toast['tone']) => void }) {
  const { taluks } = useAppData()
  const availableTaluks = taluks.filter(item => item.is_active && (!item.agent_profile_id || String(item.agent_profile_id) === String(agent.id)))
  const [statusValue, setStatusValue] = useState(String(agent.account_status)), [talukId, setTalukId] = useState(String(agent.taluk_id || ''))
  const [error, setError] = useState(''), [submitting, setSubmitting] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSubmitting(true); setError('')
    const values = new FormData(event.currentTarget)
    try {
      await workspaceApi.updateAgent(String(agent.id), { expected_version: Number(agent.version), full_name: String(values.get('full_name')).trim(), phone: String(values.get('phone')).trim() || null, account_status: statusValue, taluk_id: talukId || null, reason: String(values.get('reason')).trim() })
      await reload(); notify('Agent details updated.'); onClose()
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Agent could not be updated.') }
    finally { setSubmitting(false) }
  }
  return <Modal title="Edit collection agent" onClose={onClose}><form className="modal-form" onSubmit={submit}><section className="profile-data"><span>Login ID</span><strong>{String(agent.login_id)}</strong></section><div className="form-grid"><label>Full name<input name="full_name" required minLength={2} defaultValue={String(agent.full_name)} /></label><label>Phone<input name="phone" inputMode="tel" defaultValue={String(agent.phone || '')} /></label></div><div className="form-grid"><label>Account status<select value={statusValue} onChange={event => { const value = event.target.value; setStatusValue(value); if (value !== 'ACTIVE') setTalukId('') }}><option value="ACTIVE">Active</option><option value="INACTIVE">Inactive</option><option value="LOCKED">Locked</option></select></label><label>Taluk assignment<select value={talukId} onChange={event => setTalukId(event.target.value)} disabled={statusValue !== 'ACTIVE'}><option value="">Unassigned</option>{availableTaluks.map(item => <option value={String(item.id)} key={String(item.id)}>{String(item.name)}</option>)}</select></label></div>{talukId !== String(agent.taluk_id || '') && <p className="audit-note"><ShieldCheck /> Changing assignment ends the previous taluk bank configuration. Configure the destination bank afterward.</p>}<label>Reason for change<textarea name="reason" required minLength={3} maxLength={500} rows={2} /></label>{error && <p className="form-error"><AlertCircle />{error}</p>}<div className="modal-actions"><button className="secondary" type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={submitting}>{submitting ? 'Saving…' : 'Save changes'}</button></div></form></Modal>
}

function EditTalukModal({ taluk, onClose, reload, notify }: { taluk: Record<string, any>; onClose: () => void; reload: () => Promise<void>; notify: (message: string, tone?: Toast['tone']) => void }) {
  const [active, setActive] = useState(Boolean(taluk.is_active)), [error, setError] = useState(''), [submitting, setSubmitting] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSubmitting(true); setError('')
    const values = new FormData(event.currentTarget)
    try {
      await workspaceApi.updateTaluk(String(taluk.id), { expected_version: Number(taluk.version), code: String(values.get('code')).trim().toUpperCase(), name: String(values.get('name')).trim(), district: String(values.get('district')).trim() || null, is_active: active, reason: String(values.get('reason')).trim() })
      await reload(); notify('Taluk details updated.'); onClose()
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Taluk could not be updated.') }
    finally { setSubmitting(false) }
  }
  return <Modal title="Edit taluk" onClose={onClose}><form className="modal-form" onSubmit={submit}><div className="form-grid"><label>Taluk code<input name="code" required minLength={2} maxLength={20} pattern="[A-Za-z0-9_-]+" defaultValue={String(taluk.code)} /></label><label>Taluk name<input name="name" required minLength={2} maxLength={120} defaultValue={String(taluk.name)} /></label></div><label>District<input name="district" maxLength={120} defaultValue={String(taluk.district || '')} /></label><label className="toggle-row"><span><strong>Active taluk</strong><small>Deactivation is blocked while assignments or active members remain.</small></span><input type="checkbox" checked={active} onChange={event => setActive(event.target.checked)} /></label><label>Reason for change<textarea name="reason" required minLength={3} maxLength={500} rows={2} /></label>{error && <p className="form-error"><AlertCircle />{error}</p>}<div className="modal-actions"><button className="secondary" type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={submitting}>{submitting ? 'Saving…' : 'Save changes'}</button></div></form></Modal>
}

function ReplaceBankModal({ taluk, onClose, reload, notify }: { taluk: Record<string, any>; onClose: () => void; reload: () => Promise<void>; notify: (message: string, tone?: Toast['tone']) => void }) {
  const [error, setError] = useState(''), [submitting, setSubmitting] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSubmitting(true); setError('')
    const values = new FormData(event.currentTarget)
    try {
      await workspaceApi.replaceBank(String(taluk.bank_account_id), { taluk_id: String(taluk.id), agent_profile_id: String(taluk.agent_profile_id), bank_name: String(values.get('bank_name')).trim(), branch_name: String(values.get('branch_name')).trim(), account_holder_name: String(values.get('account_holder_name')).trim(), account_number: String(values.get('account_number')).trim(), ifsc_code: String(values.get('ifsc_code')).trim().toUpperCase(), reason: String(values.get('reason')).trim() })
      await reload(); notify('Bank account replaced. The previous account remains in history.'); onClose()
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Bank account could not be replaced.') }
    finally { setSubmitting(false) }
  }
  return <Modal title="Replace bank account" onClose={onClose}><form className="modal-form" onSubmit={submit}><section className="bank-destination"><Landmark /><div><span>Current account</span><strong>{String(taluk.bank_name)} ···· {String(taluk.bank_last4)}</strong><small>{String(taluk.name)} Taluk</small></div></section><div className="form-grid"><label>Bank name<input name="bank_name" required minLength={2} defaultValue={String(taluk.bank_name || '')} /></label><label>Branch name<input name="branch_name" required minLength={2} defaultValue={String(taluk.bank_branch_name || '')} /></label></div><label>Account holder name<input name="account_holder_name" required minLength={2} defaultValue={String(taluk.bank_account_holder_name || '')} /></label><div className="form-grid"><label>New account number<input name="account_number" required minLength={6} inputMode="numeric" pattern="[0-9]+" /></label><label>IFSC code<input name="ifsc_code" required pattern="[A-Za-z]{4}0[A-Za-z0-9]{6}" defaultValue={String(taluk.bank_ifsc_code || '')} /></label></div><label>Reason for replacement<textarea name="reason" required minLength={3} maxLength={500} rows={2} /></label>{error && <p className="form-error"><AlertCircle />{error}</p>}<div className="modal-actions"><button className="secondary" type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={submitting}>{submitting ? 'Replacing…' : 'Replace account'}</button></div></form></Modal>
}

function EditMemberModal({ member, onClose, reload, notify }: { member: MemberRecord; onClose: () => void; reload: () => Promise<void>; notify: (message: string, tone?: Toast['tone']) => void }) {
  const { taluks } = useAppData()
  const readyTaluks = taluks.filter(item => item.is_active && item.agent_name)
  const [error, setError] = useState(''), [submitting, setSubmitting] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSubmitting(true); setError('')
    const values = new FormData(event.currentTarget)
    try {
      await workspaceApi.updateMember(member.id, { expected_version: Number(member.version), profile_expected_version: Number(member.profileVersion), member_code: String(values.get('member_code')).trim().toUpperCase(), ard_no: String(values.get('ard_no')).trim() || null, full_name: String(values.get('full_name')).trim(), phone: String(values.get('phone')).trim() || null, taluk_id: String(values.get('taluk_id')), joined_on: String(values.get('joined_on')), account_status: String(values.get('account_status')).toUpperCase(), reason: String(values.get('reason')).trim() })
      await reload(); notify('Member details updated.'); onClose()
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Member could not be updated.') }
    finally { setSubmitting(false) }
  }
  return <Modal title="Edit member" onClose={onClose}><form className="modal-form" onSubmit={submit}>
    <div className="form-grid"><label>Member code<input name="member_code" required minLength={2} maxLength={40} defaultValue={member.code} /></label><label>ARD number <small>(optional)</small><input name="ard_no" inputMode="numeric" pattern="[0-9]+" maxLength={30} defaultValue={member.ardNo || ''} /></label></div>
    <div className="form-grid"><label>Account status<select name="account_status" defaultValue={member.status.toUpperCase()}><option value="ACTIVE">Active</option><option value="INACTIVE">Inactive</option><option value="LOCKED">Locked</option></select></label><label>Joined on<input name="joined_on" type="date" required max={new Date().toISOString().slice(0, 10)} defaultValue={member.joinedOn} /></label></div>
    <div className="form-grid"><label>Full name<input name="full_name" required minLength={2} defaultValue={member.name} /></label><label>Phone<input name="phone" inputMode="tel" defaultValue={member.phone} /></label></div>
    <label>Taluk<select name="taluk_id" required defaultValue={member.talukId}>{readyTaluks.map(item => <option value={String(item.id)} key={String(item.id)}>{String(item.name)}</option>)}</select></label>
    <label>Reason for change<textarea name="reason" required minLength={3} maxLength={500} rows={2} /></label>{error && <p className="form-error"><AlertCircle />{error}</p>}<div className="modal-actions"><button className="secondary" type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={submitting}>{submitting ? 'Saving…' : 'Save changes'}</button></div>
  </form></Modal>
}

function InitialSetupModal({ kind, onClose, reload, notify }: { kind: SetupKind; onClose: () => void; reload: () => Promise<void>; notify: (message: string, tone?: Toast['tone']) => void }) {
  const { taluks, agents } = useAppData()
  const [error, setError] = useState(''), [submitting, setSubmitting] = useState(false)
  const availableAgentTaluks = taluks.filter(item => !item.agent_name)
  const availableBankAgents = agents.filter(agent => !taluks.find(item => String(item.id) === String(agent.taluk_id))?.bank_name)
  const readyTaluks = taluks.filter(item => item.agent_name)
  const titles: Record<SetupKind, string> = { taluk: 'Add taluk', agent: 'Add collection agent', bank: 'Configure bank account', member: 'Add member' }
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSubmitting(true); setError('')
    const values = new FormData(event.currentTarget)
    try {
      if (kind === 'taluk') await workspaceApi.createTaluk({ code: String(values.get('code')).trim().toUpperCase(), name: String(values.get('name')).trim(), district: String(values.get('district')).trim() || null })
      if (kind === 'agent') await workspaceApi.createAgent({ login_id: String(values.get('login_id')).trim(), temporary_password: String(values.get('temporary_password')), full_name: String(values.get('full_name')).trim(), phone: String(values.get('phone')).trim(), taluk_id: String(values.get('taluk_id')) })
      if (kind === 'member') await workspaceApi.createMember({ login_id: String(values.get('login_id')).trim(), temporary_password: String(values.get('temporary_password')), member_code: String(values.get('member_code')).trim().toUpperCase(), ard_no: String(values.get('ard_no')).trim() || null, full_name: String(values.get('full_name')).trim(), phone: String(values.get('phone')).trim(), taluk_id: String(values.get('taluk_id')), joined_on: String(values.get('joined_on')) })
      if (kind === 'bank') {
        const agent = agents.find(item => String(item.id) === String(values.get('agent_profile_id')))
        if (!agent) throw new Error('Select an agent.')
        await workspaceApi.createBank({ taluk_id: String(agent.taluk_id), agent_profile_id: String(agent.id), bank_name: String(values.get('bank_name')).trim(), branch_name: String(values.get('branch_name')).trim(), account_holder_name: String(values.get('account_holder_name')).trim(), account_number: String(values.get('account_number')).trim(), ifsc_code: String(values.get('ifsc_code')).trim().toUpperCase() })
      }
      await reload(); notify(`${titles[kind]} completed.`); onClose()
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Setup could not be saved.') }
    finally { setSubmitting(false) }
  }
  return <Modal title={titles[kind]} onClose={onClose}><form className="modal-form" onSubmit={submit}>
    {kind === 'taluk' && <><div className="form-grid"><label>Taluk code<input name="code" required minLength={2} maxLength={20} pattern="[A-Za-z0-9_-]+" placeholder="KTM" /></label><label>Taluk name<input name="name" required minLength={2} maxLength={120} placeholder="Kottayam" /></label></div><label>District <small>(optional)</small><input name="district" maxLength={120} /></label></>}
    {kind === 'agent' && <><label>Taluk<select name="taluk_id" required defaultValue=""><option value="" disabled>Select an unassigned taluk</option>{availableAgentTaluks.map(item => <option value={String(item.id)} key={String(item.id)}>{String(item.name)}</option>)}</select></label><div className="form-grid"><label>Full name<input name="full_name" required minLength={2} /></label><label>Phone<input name="phone" required inputMode="tel" /></label></div><label>Login ID<input name="login_id" required autoComplete="off" /></label><label>Temporary password<input name="temporary_password" type="password" required minLength={8} autoComplete="new-password" /></label></>}
    {kind === 'bank' && <><label>Assigned agent<select name="agent_profile_id" required defaultValue=""><option value="" disabled>Select an agent without a bank</option>{availableBankAgents.map(item => <option value={String(item.id)} key={String(item.id)}>{String(item.full_name)} - {String(item.taluk_name)}</option>)}</select></label><div className="form-grid"><label>Bank name<input name="bank_name" required minLength={2} /></label><label>Branch name<input name="branch_name" required minLength={2} /></label></div><label>Account holder name<input name="account_holder_name" required minLength={2} /></label><div className="form-grid"><label>Account number<input name="account_number" required minLength={6} inputMode="numeric" pattern="[0-9]+" /></label><label>IFSC code<input name="ifsc_code" required pattern="[A-Za-z]{4}0[A-Za-z0-9]{6}" placeholder="ABCD0123456" /></label></div></>}
    {kind === 'member' && <><label>Taluk<select name="taluk_id" required defaultValue=""><option value="" disabled>Select a configured taluk</option>{readyTaluks.map(item => <option value={String(item.id)} key={String(item.id)}>{String(item.name)}</option>)}</select></label><div className="form-grid"><label>Member code<input name="member_code" required minLength={2} maxLength={30} /></label><label>ARD number <small>(optional)</small><input name="ard_no" inputMode="numeric" pattern="[0-9]+" maxLength={30} /></label></div><div className="form-grid"><label>Joined on<input name="joined_on" type="date" required max={new Date().toISOString().slice(0, 10)} /></label><label>Phone<input name="phone" required inputMode="tel" /></label></div><label>Full name<input name="full_name" required minLength={2} /></label><label>Login ID<input name="login_id" required autoComplete="off" /></label><label>Temporary password<input name="temporary_password" type="password" required minLength={8} autoComplete="new-password" /></label></>}
    {error && <p className="form-error"><AlertCircle />{error}</p>}
    <div className="modal-actions"><button className="secondary" type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit" disabled={submitting}>{submitting ? 'Saving…' : 'Save'}</button></div>
  </form></Modal>
}

function ReportsPage() {
  const { cases, members } = useAppData()
  const collected = cases.reduce((sum, item) => sum + item.collected, 0), verified = cases.reduce((sum, item) => sum + item.verified, 0)
  const exportDues = () => downloadCsv(`outstanding-dues-${new Date().toISOString().slice(0, 10)}.csv`, [['Member code', 'Member name', 'Taluk', 'Pending amount'], ...members.map(item => [item.code, item.name, item.taluk, item.pending])])
  const exportCases = () => downloadCsv(`death-cases-${new Date().toISOString().slice(0, 10)}.csv`, [['Case number', 'Deceased member', 'Taluk', 'Death date', 'Status', 'Required', 'Collected', 'Verified'], ...cases.map(item => [item.caseNumber, item.name, item.taluk, item.deathDate, item.status, item.requiredTotal, item.collected, item.verified])])
  return <div className="page-stack"><section className="report-banner"><div><span>All recorded collections</span><strong>{<Money value={collected} />}</strong><small>{<Money value={verified} />} verified</small></div></section><div className="report-list"><button onClick={exportDues}><IndianRupee /><span><strong>Outstanding dues</strong><small>{<Money value={members.reduce((sum, item) => sum + item.pending, 0)} />} across {members.length} members</small></span><Download /></button><button onClick={exportCases}><CalendarDays /><span><strong>Death cases</strong><small>{cases.length} records</small></span><Download /></button></div></div>
}

function CreateCaseModal({ onClose, onPublish }: { onClose: () => void; onPublish: (caseId: string) => void | Promise<void> }) {
  const { members } = useAppData()
  const [preview, setPreview] = useState<Record<string, any> | null>(null)
  const [override, setOverride] = useState(false), [error, setError] = useState(''), [submitting, setSubmitting] = useState(false)
  useEffect(() => { workspaceApi.casePreview().then(setPreview).catch(error => setError(error.message)) }, [])
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSubmitting(true); setError('')
    try {
      const values = new FormData(event.currentTarget)
      const memberId = String(values.get('member_id') || ''), details = String(values.get('details') || '').trim()
      const member = members.find(item => item.id === memberId), photo = values.get('photo')
      if (!member || !(photo instanceof File) || !photo.size) throw new Error('Select a member and photo.')
      const upload = await workspaceApi.uploadCasePhoto(photo)
      const created = await workspaceApi.publishCase({
        deceased_member_id: memberId, death_date: String(values.get('death_date')),
        title: `Helping request for ${member.name}`, details, photo_object_path: upload.object_path,
        contribution_amount_override: override ? Number(values.get('override_amount')) : null,
        override_reason: override ? String(values.get('override_reason') || '') : null,
      })
      await onPublish(String(created.id))
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'The case could not be published.') }
    finally { setSubmitting(false) }
  }
  return <Modal title="Create death case" onClose={onClose}><form onSubmit={submit} className="modal-form"><label>Deceased member<select name="member_id" required defaultValue=""><option value="" disabled>Select active member</option>{members.filter(item => item.status === 'Active').map(item => <option value={item.id} key={item.id}>{item.code} — {item.name}</option>)}</select></label><label>Date of death<input name="death_date" type="date" required max={new Date().toISOString().slice(0, 10)} /></label><label>Case details<textarea name="details" required minLength={3} placeholder="Enter member-visible details" rows={3} /></label><label>Member photo<input name="photo" required type="file" accept="image/jpeg,image/png,image/webp" /></label>{preview && <section className="rate-preview"><div><span>Next monthly sequence</span><strong>Case {String(preview.next_sequence)}</strong></div><div><span>Default contribution</span><strong>{<Money value={Number(preview.default_amount)} />}</strong></div></section>}<label className="toggle-row"><span><strong>Override contribution amount</strong><small>A reason is required and will be audited.</small></span><input type="checkbox" checked={override} onChange={event => setOverride(event.target.checked)} /></label>{override && <div className="form-grid"><label>Contribution amount<input name="override_amount" type="number" min="1" step="0.01" required  onInput={normalizeMoneyInput} inputMode="decimal"/></label><label>Override reason<textarea name="override_reason" required minLength={3} rows={2} /></label></div>}{error && <p className="form-error"><AlertCircle />{error}</p>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button className="primary" disabled={submitting} type="submit">{submitting ? 'Publishing…' : 'Publish case'}</button></div></form></Modal>
}

function AdminCollectionBatchModal({ onClose, onRecorded }: { onClose: () => void; onRecorded: (amount: number) => void | Promise<void> }) {
  const { agents, members } = useAppData()
  const activeAgents = agents.filter(agent => agent.account_status === 'ACTIVE' && agent.taluk_id)
  const [agentId, setAgentId] = useState(String(activeAgents[0]?.id || ''))
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<Record<string, number>>({})
  const [method, setMethod] = useState<CollectionRecord['method']>('Cash')
  const [reference, setReference] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const agent = activeAgents.find(item => String(item.id) === agentId)
  const talukMembers = members.filter(member => member.status === 'Active' && member.talukId === String(agent?.taluk_id))
  const targets = talukMembers.flatMap(member => {
    const obligations = (member.obligations || []).filter(item => item.available > 0).map(item => ({
      key: `case:${item.id}`, member, label: item.label, available: item.available,
      collection_type: 'DEATH_CONTRIBUTION', case_obligation_id: item.id, permanent_account_id: null,
    }))
    const permanentAvailable = member.permanentAccountId ? Math.max((member.permanentTarget || 0) - (member.permanentCollected || 0), 0) : 0
    return permanentAvailable > 0 ? [...obligations, {
      key: `permanent:${member.permanentAccountId}`, member, label: 'Permanent membership', available: permanentAvailable,
      collection_type: 'PERMANENT_MEMBERSHIP', case_obligation_id: null, permanent_account_id: member.permanentAccountId || null,
    }] : obligations
  })
  const visible = targets.filter(item => {
    const term = query.trim().toLowerCase()
    return !term || item.member.name.toLowerCase().includes(term) || item.member.code.toLowerCase().includes(term) || item.label.toLowerCase().includes(term)
  })
  const total = Object.values(selected).reduce((sum, amount) => sum + Number(amount || 0), 0)
  const toggle = (key: string, available: number) => setSelected(current => {
    const next = { ...current }
    if (key in next) delete next[key]
    else next[key] = available
    return next
  })
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError('')
    const entries = targets.filter(item => selected[item.key] > 0).map(item => ({
      member_id: item.member.id, collection_type: item.collection_type,
      case_obligation_id: item.case_obligation_id, permanent_account_id: item.permanent_account_id,
      amount: selected[item.key], method: method.toUpperCase().replaceAll(' ', '_'),
    }))
    if (!agentId || !entries.length || total <= 0) { setError('Select an agent and at least one payment.'); return }
    setSubmitting(true)
    try {
      await workspaceApi.createAdminCollectionBatch({
        client_request_id: crypto.randomUUID(), agent_profile_id: agentId, entries,
        declared_amount: total, received_at: new Date().toISOString(),
        reference: reference.trim() || null, note: note.trim() || null,
      })
      await onRecorded(total)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Collection batch could not be recorded.') }
    finally { setSubmitting(false) }
  }
  return <Modal title="Record collection batch" onClose={onClose} wide><form className="modal-form" onSubmit={submit}>
    <section className="bank-destination"><ShieldCheck /><div><span>Administrator verification</span><strong>Record money received from the assigned agent</strong><small>Selected payments are verified immediately and added to member history.</small></div></section>
    <div className="form-grid"><label>Collection agent<select required value={agentId} onChange={event => { setAgentId(event.target.value); setSelected({}) }}><option value="" disabled>Select agent</option>{activeAgents.map(item => <option value={String(item.id)} key={String(item.id)}>{String(item.full_name)} · {String(item.taluk_name || '')}</option>)}</select></label><label>Method<select value={method} onChange={event => setMethod(event.target.value as CollectionRecord['method'])}><option>Cash</option><option>UPI</option><option>Bank transfer</option><option>Other</option></select></label></div>
    {agentId && <><SearchBox value={query} onChange={setQuery} placeholder="Search member, code, or case" /><div className="select-head"><span>{Object.keys(selected).length} payments selected</span><button type="button" onClick={() => setSelected({})}>Clear all</button></div><div className="collection-select admin-collection-select">{visible.map(item => <label key={item.key}><input type="checkbox" checked={item.key in selected} onChange={() => toggle(item.key, item.available)} /><span><strong>{item.member.name}</strong><small>{item.member.code} · {item.label}</small></span>{item.key in selected ? <input aria-label={`Amount for ${item.member.name} ${item.label}`} className="entry-amount" type="number" min="0.01" max={item.available} step="0.01" value={selected[item.key]} onChange={event => setSelected(current => ({ ...current, [item.key]: Number(event.target.value) }))} onInput={normalizeMoneyInput} /> : <b><Money value={item.available} /></b>}</label>)}</div>{!visible.length && <p className="subtle">No outstanding payments match this selection.</p>}</>}
    <section className="calculated-total"><span>Amount received and verified</span><strong><Money value={total} /></strong></section>
    <div className="form-grid"><label>Reference <span className="optional-label">Optional</span><input value={reference} onChange={event => setReference(event.target.value)} maxLength={500} placeholder="Receipt or acknowledgement" /></label><label>Note <span className="optional-label">Optional</span><input value={note} onChange={event => setNote(event.target.value)} maxLength={1000} placeholder="Cash count or collection details" /></label></div>
    {error && <p className="form-error"><AlertCircle />{error}</p>}<div className="audit-note"><ShieldCheck /> The administrator is recorded as the verifier; the selected agent remains the physical collector.</div><div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button className="primary" disabled={submitting || !agentId || total <= 0}>{submitting ? 'Recording…' : `Record ${formatMoney(total)}`}</button></div>
  </form></Modal>
}

function CollectionModal({ initialMemberId, onClose, onRecord }: { initialMemberId?: string; onClose: () => void; onRecord: (memberId: string, type: string, amount: number, method: CollectionRecord['method']) => void | Promise<void> }) {
  const { members } = useAppData()
  const activeMembers = members.filter(item => item.status === 'Active')
  const [memberId, setMemberId] = useState(activeMembers.some(item => item.id === initialMemberId) ? initialMemberId! : activeMembers[0]?.id || '')
  const member = members.find(item => item.id === memberId)
  const targets = [
    ...(member?.obligations || []).filter(item => item.available > 0).map(item => ({ value: item.caseId, label: item.label, available: item.available })),
    ...(member?.permanentAccountId && (member.permanentCollected || 0) < (member.permanentTarget || 0)
      ? [{ value: 'permanent', label: 'Permanent membership', available: (member.permanentTarget || 0) - (member.permanentCollected || 0) }] : [])
  ]
  const [target, setTarget] = useState(''), [amount, setAmount] = useState<number | ''>('')
  const [method, setMethod] = useState<CollectionRecord['method']>('Cash'), [error, setError] = useState(''), [submitting, setSubmitting] = useState(false)
  const selected = targets.find(item => item.value === target) || targets[0]
  useEffect(() => { setTarget(''); setAmount('') }, [memberId])
  useEffect(() => { if (selected) setAmount(selected.available) }, [memberId, selected?.value])
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!member || !selected) { setError('This member has no collectible balance.'); return }
    if (amount === '' || amount <= 0) { setError('Enter a valid amount.'); return }
    setSubmitting(true); setError('')
    try { await onRecord(member.id, selected.value, Number(amount), method) }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Collection could not be recorded.') }
    finally { setSubmitting(false) }
  }
  return <Modal title="Record payment" onClose={onClose}><form className="modal-form" onSubmit={submit}><label>Member<select value={memberId} onChange={event => setMemberId(event.target.value)}>{members.filter(item => item.status === 'Active').map(item => <option value={item.id} key={item.id}>{item.code} — {item.name}</option>)}</select></label><label>Collection for<select value={selected?.value || ''} onChange={event => { setTarget(event.target.value); const next = targets.find(item => item.value === event.target.value); setAmount(next?.available || '') }}>{targets.map(item => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label>{selected && <section className="balance-box"><span>Available balance</span><strong>{<Money value={selected.available} />}</strong><small>Already collected amounts are excluded.</small></section>}<div className="form-grid"><label>Amount<input type="number" min="1" max={selected?.available || 0} step="0.01" value={amount} onChange={event => setAmount(event.target.value === '' ? '' : Number(event.target.value))} onInput={normalizeMoneyInput} inputMode="decimal" /></label><label>Method<select value={method} onChange={event => setMethod(event.target.value as CollectionRecord['method'])}><option>Cash</option><option>UPI</option><option>Bank transfer</option><option>Other</option></select></label></div>{error && <p className="form-error"><AlertCircle />{error}</p>}<div className="audit-note"><ShieldCheck /> This creates an auditable collection entry. It cannot be silently deleted.</div><div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button className="primary" disabled={submitting || !selected || amount === '' || amount <= 0} type="submit"><IndianRupee />{submitting ? 'Recording…' : amount === '' ? 'Enter amount' : `Record ${formatAmount(amount)}`}</button></div></form></Modal>
}

function DepositModal({ collections, onClose, onSubmit }: { collections: CollectionRecord[]; onClose: () => void; onSubmit: (ids: string[], amount: number, note: string) => void | Promise<void> }) {
  const [selected, setSelected] = useState<string[]>(collections.map(item => item.id))
  const [declared, setDeclared] = useState<number | ''>(0), [note, setNote] = useState('')
  const [error, setError] = useState(''), [submitting, setSubmitting] = useState(false)
  const total = collections.filter(item => selected.includes(item.id)).reduce((sum, item) => sum + item.amount, 0)
  useEffect(() => setDeclared(total), [total])
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setSubmitting(true); setError('')
    try { await onSubmit(selected, Number(declared), note) }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Handover could not be submitted.') }
    finally { setSubmitting(false) }
  }
  return <Modal title="Prepare collection handover" onClose={onClose} wide><form className="modal-form" onSubmit={submit}><section className="bank-destination"><WalletCards /><div><span>Handover recipient</span><strong>Karunya Sparsham administrator</strong><small>The administrator confirms the amount after receiving it.</small></div></section><div className="select-head"><span>{selected.length} collection entries selected</span><button type="button" onClick={() => setSelected(selected.length === collections.length ? [] : collections.map(item => item.id))}>{selected.length === collections.length ? 'Clear all' : 'Select all'}</button></div><div className="collection-select">{collections.map(item => <label key={item.id}><input type="checkbox" checked={selected.includes(item.id)} onChange={() => setSelected(selected.includes(item.id) ? selected.filter(id => id !== item.id) : [...selected, item.id])} /><span><strong>{item.member}</strong><small>{item.label} · {item.receipt}</small></span><b>{<Money value={item.amount} />}</b></label>)}</div><section className="calculated-total"><span>System-calculated total</span><strong>{<Money value={total} />}</strong></section><div className="form-grid"><label>Amount handed over<input type="number" step="0.01" min="0" value={declared} onChange={event => setDeclared(event.target.value === '' ? '' : Number(event.target.value))} onInput={normalizeMoneyInput} inputMode="decimal" /></label><label>Handover note <span className="optional-label">Optional</span><input value={note} onChange={event => setNote(event.target.value)} maxLength={1000} placeholder="Add cash count or handover details" /></label></div>{declared !== total && <p className="form-error"><AlertCircle /> The handed-over amount must exactly match {<Money value={total} />}.</p>}{error && <p className="form-error"><AlertCircle />{error}</p>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button className="primary" disabled={submitting || !selected.length || declared === '' || declared !== total} type="submit">{submitting ? 'Submitting…' : 'Submit handover'}</button></div></form></Modal>
}

function DepositAdminNotice({ notice, onClose }: { notice: { number: string; amount: number; note: string; submitted: string; href: string }; onClose: () => void }) {
  return <Modal title="Handover submitted" onClose={onClose}><div className="modal-form"><section className="bank-destination"><FaWhatsapp /><div><span>Admin WhatsApp</span><strong>+91 94476 45196</strong><small>Collection handover notification</small></div></section><div className="profile-data"><span>Handover</span><strong>{notice.number}</strong><span>Amount</span><strong>{<Money value={notice.amount} />}</strong><span>Note</span><strong>{notice.note}</strong><span>Submitted</span><strong>{notice.submitted}</strong></div><div className="audit-note"><ShieldCheck /> കൈമാറിയ തുകയും കളക്ഷൻ വിവരങ്ങളും അഡ്മിനുമായി സ്ഥിരീകരിക്കുക.</div><div className="modal-actions"><button className="secondary" type="button" onClick={onClose}>Close</button><a className="primary admin-whatsapp-action" href={notice.href} target="_blank" rel="noreferrer"><FaWhatsapp /> WhatsApp admin</a></div></div></Modal>
}

function Modal({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return <div className="modal-wrap" role="dialog" aria-modal="true"><button className="modal-scrim" onClick={onClose} aria-label="Close dialog backdrop" /><section className={`modal ${wide ? 'wide' : ''}`}><header><h2>{title}</h2><button className="icon-btn" onClick={onClose} aria-label="Close dialog"><X /></button></header><div className="modal-body">{children}</div></section></div>
}

function Metric({ icon: Icon, label, value, detail, tone = '' }: { icon: LucideIcon; label: string; value: ReactNode; detail?: string; tone?: string }) {
  return <article className={`metric ${tone}`}><div className="metric-icon"><Icon /></div><div><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div></article>
}
function SectionHeading({ title, action, onAction }: { title: string; action?: string; onAction?: () => void }) { return <div className="section-heading"><h2>{title}</h2>{action && <button onClick={onAction}>{action}<ChevronRight /></button>}</div> }
function Progress({ value }: { value: number }) { return <div className="progress" aria-label={`${Math.round(value)}%`}><i style={{ width: `${Math.min(value, 100)}%` }} /></div> }
function SearchBox({ placeholder, value, onChange }: { placeholder: string; value?: string; onChange?: (value: string) => void }) { return <label className="search-box"><Search /><input placeholder={placeholder} value={value} onChange={e => onChange?.(e.target.value)} /></label> }
function Avatar({ name, color, large = false }: { name: string; color: string; large?: boolean }) { return <div className={`avatar ${large ? 'large' : ''}`} style={{ background: color }}>{initials(name)}</div> }
function CasePhoto({ item, large = false }: { item: CaseRecord; large?: boolean }) {
  const [failed, setFailed] = useState(false)
  if (!item.photoUrl || failed) return <Avatar name={item.name} color={item.accent} large={large} />
  return <img className={`case-photo ${large ? 'large' : ''}`} src={item.photoUrl} alt={`Photo of ${item.name}`} onError={() => setFailed(true)} />
}
function Status({ value }: { value: string }) { const key = value.toLowerCase().replaceAll(' ', '-'); return <span className={`status ${key}`}>{['Verified', 'Approved', 'Received', 'Active', 'Permanent', 'Closed'].includes(value) ? <CheckCircle2 /> : value === 'Rejected' ? <XCircle /> : <Clock3 />}{value}</span> }
function HandoverStatus({ value }: { value: DepositRecord['status'] }) {
  const label = value === 'Approved' ? 'Received' : value === 'Submitted' ? 'Awaiting receipt' : value
  return <Status value={label} />
}

function CaseCard({ item, onClick, memberDue, agent = false }: { item: CaseRecord; onClick: () => void; memberDue?: DueRecord; agent?: boolean }) {
  const pct = item.requiredTotal ? Math.min((item.collected / item.requiredTotal) * 100, 100) : 0
  return <article className="case-card" role="button" tabIndex={0} onClick={onClick} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onClick() } }}><div className="case-card-main"><CasePhoto item={item} /><div><span className="case-number">{item.caseNumber}</span><h3>{item.name}</h3><p><CalendarDays /> {item.deathDate} · {item.taluk}</p></div><ChevronRight className="chevron" /></div>{memberDue ? <div className="case-obligation"><div><span>Your contribution</span><strong>{<Money value={memberDue.required} />}</strong></div><Status value={getMoneyStatus(memberDue.required, memberDue.collected, memberDue.verified)} /></div> : <div className="case-progress"><div><span>{agent ? 'Taluk collected' : 'Collection progress'}</span><strong>{Math.round(pct)}%</strong></div><Progress value={pct} /><small>{<Money value={item.collected} />} collected · {<Money value={item.verified} />} verified</small></div>}</article>
}

function LedgerBreakdown({ required, collected, verified }: { required: number; collected: number; verified: number }) {
  return <div className="ledger"><div><span>Required</span><strong>{<Money value={required} />}</strong></div><div><span>Collected</span><strong>{<Money value={collected} />}</strong></div><div><span>Awaiting</span><strong>{<Money value={collected - verified} />}</strong></div><div><span>Verified</span><strong>{<Money value={verified} />}</strong></div><div className="remaining"><span>Still to give agent</span><strong>{<Money value={required - collected} />}</strong></div></div>
}

function DepositRow({ deposit, admin = false, onClick, selected = false, action, actionLabel }: { deposit: DepositRecord; admin?: boolean; onClick?: () => void; selected?: boolean; action?: () => void; actionLabel?: string }) {
  return <article className={`deposit-row ${onClick ? 'interactive' : ''} ${selected ? 'selected' : ''}`} role={onClick ? 'button' : undefined} tabIndex={onClick ? 0 : undefined} onClick={onClick} onKeyDown={event => { if (onClick && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onClick() } }}><div className="deposit-icon"><WalletCards /></div><div><span>{deposit.number}</span><strong>{admin ? deposit.agent : deposit.taluk}</strong><small>{deposit.submitted}</small></div><div><strong>{<Money value={deposit.calculated} />}</strong><HandoverStatus value={deposit.status} /></div>{action ? <button className="small-action" onClick={event => { event.stopPropagation(); action() }}><ArrowRight />{actionLabel}</button> : onClick && <ChevronRight />}</article>
}

function MemberRow({ member, pending = member.pending, action, actionLabel = 'Record payment', onClick }: { member: MemberRecord; pending?: number; action?: () => void; actionLabel?: string; onClick?: () => void }) {
  return <article className={`member-row ${onClick ? 'interactive' : ''}`} role={onClick ? 'button' : undefined} tabIndex={onClick ? 0 : undefined} onClick={onClick} onKeyDown={event => { if (onClick && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onClick() } }}><div className="avatar">{initials(member.name)}</div><div><span>{member.code}{member.ardNo ? ` · ARD ${member.ardNo}` : ''}</span><strong>{member.name}</strong><small>{member.phone} · {member.membership} · {member.status}</small></div><div className="member-due"><span>Pending</span><strong>{<Money value={pending} />}</strong></div>{action ? <button className="small-action" onClick={e => { e.stopPropagation(); action() }}>{actionLabel === 'Edit' ? <Pencil /> : <IndianRupee />}{actionLabel}</button> : onClick && <ChevronRight />}</article>
}

function initials(name: string) { return name.split(' ').map(n => n[0]).slice(0, 2).join('').toUpperCase() }
function MapPinIcon() { return <Landmark /> }

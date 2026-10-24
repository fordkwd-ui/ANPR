import React, { useState, useEffect, useRef } from 'react';
import {
  Shield,
  Activity,
  Truck,
  Car,
  Camera,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Search,
  Download,
  LogIn,
  LogOut,
  Edit3,
  Video,
  X,
  RefreshCw,
  HardDrive,
  Layers,
  Volume2,
  VolumeX,
  PlusCircle,
  LayoutGrid,
  List,
  Check,
  Trash2,
  Bike,
  FileText,
  Maximize2,
  Eye,
  ExternalLink,
  Filter,
  Calendar,
  SlidersHorizontal,
  Lock,
  UserCheck,
  Users,
  UserPlus,
  ShieldAlert,
} from 'lucide-react';
import { ScheduleDate } from './components/ScheduleDate';
import { Pagination5 } from './components/Pagination5';

// Use relative paths to seamlessly route via Vite dev proxy on 5173 or Caddy in production
const API_BASE = import.meta.env.VITE_API_BASE ?? '';
const WS_BASE = import.meta.env.VITE_WS_BASE ?? (
  window.location.protocol === 'https:' ? `wss://${window.location.host}` : `ws://${window.location.host}`
);

// Timezone-aware date parser guaranteeing UTC interpretation for naive ISO strings
function parseUtcDate(dateString) {
  if (!dateString) return new Date();
  if (typeof dateString !== 'string') return new Date(dateString);
  // If string has no timezone offset (Z or +/-HH:MM), treat as UTC
  if (!dateString.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(dateString)) {
    return new Date(dateString + 'Z');
  }
  return new Date(dateString);
}

// Format local transit time in Indian Standard Time (IST: Asia/Kolkata)
function formatTransitTime(dateString) {
  if (!dateString) return '';
  const date = parseUtcDate(dateString);
  try {
    return date.toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }) + ' IST';
  } catch (e) {
    return date.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' IST';
  }
}

// Format relative time helper for quick field scanning (0s ago, 5s ago, 2m ago)
function formatTimeAgo(dateString) {
  if (!dateString) return '';
  const now = new Date();
  const date = parseUtcDate(dateString);
  const diffSec = Math.max(0, Math.floor((now - date) / 1000));

  if (diffSec < 5) return 'just now';
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.floor(diffHr / 24)}d ago`;
}

// Authentic Indian High Security Registration Plate (HSRP) Subcomponent
function HsrpPlate({ plate, rawPlate, isValid = true }) {
  const displayPlate = (plate || rawPlate || 'UNKNOWN').toUpperCase();

  return (
    <div
      className={`hsrp-plate ${isValid ? '' : 'invalid'}`}
      title={isValid ? 'Official HSRP Plate (Valid format)' : 'Unrecognized plate format — Manual check required'}
    >
      <div className="hsrp-plate-blue-strip">
        <div className="hsrp-chakra-symbol" />
        <span className="hsrp-ind-text">IND</span>
      </div>
      <div className="hsrp-number">
        {displayPlate}
      </div>
    </div>
  );
}

export default function App() {
  // Authentication State
  const [token, setToken] = useState(localStorage.getItem('gate_token') || '');
  const [currentUser, setCurrentUser] = useState(
    JSON.parse(localStorage.getItem('gate_user') || 'null')
  );
  const [loginForm, setLoginForm] = useState({ username: '', password: '' });
  const [loginError, setLoginError] = useState('');
  const [loginLoading, setLoginLoading] = useState(false);
  const [showUsersModal, setShowUsersModal] = useState(false);
  const [usersList, setUsersList] = useState([]);
  const [newUserForm, setNewUserForm] = useState({ username: '', password: '', role: 'reviewer' });
  const [userFormError, setUserFormError] = useState('');

  // Primary Navigation Tab: 'live_24h' (Front Page) vs 'archives' (Second Page)
  const [activeTab, setActiveTab] = useState('live_24h');

  // Live Telemetry & Records State
  const [detections, setDetections] = useState([]);
  const [stats, setStats] = useState({ vehicles: 0, trucks: 0, loaded: 0, needs_review: 0 });
  const [health, setHealth] = useState({ online: false, camera_a_ok: false, camera_b_ok: false, disk_used_pct: 0 });
  const [latency, setLatency] = useState(null);
  const [wsConnected, setWsConnected] = useState(false);

  // Field UX Options
  const [viewMode, setViewMode] = useState('table'); // 'table' | 'cards'
  const [audioEnabled, setAudioEnabled] = useState(true);
  const [toastMessage, setToastMessage] = useState('');
  const [isSimulating, setIsSimulating] = useState(false);

  // Filters & Search for Live Page
  const [searchPlate, setSearchPlate] = useState('');
  const [filterVehicleType, setFilterVehicleType] = useState('');
  const [filterLoadType, setFilterLoadType] = useState('');
  const [filterStatus, setFilterStatus] = useState('');

  // Multi-day & Footage Archive States (Second Page)
  const [archivePreset, setArchivePreset] = useState('7d');
  const [archiveRange, setArchiveRange] = useState(() => {
    const today = new Date();
    today.setHours(23, 59, 59, 999);
    const past = new Date();
    past.setHours(0, 0, 0, 0);
    past.setTime(past.getTime() - 6 * 86400000);
    return { start: past, end: today };
  });
  const [showScheduleModal, setShowScheduleModal] = useState(false);
  const [archivePage, setArchivePage] = useState(1);
  const [archivePageSize, setArchivePageSize] = useState(10);
  const [archiveSearchPlate, setArchiveSearchPlate] = useState('');
  const [archiveVehicleType, setArchiveVehicleType] = useState('');
  const [archiveLoadType, setArchiveLoadType] = useState('');
  const [archiveStatus, setArchiveStatus] = useState('');

  // Modals & Active Selections
  const [editingDetection, setEditingDetection] = useState(null);
  const [correctionForm, setCorrectionForm] = useState({ plate: '', vehicle_type: '', load_type: '' });
  const [activeDossier, setActiveDossier] = useState(null);
  const [zoomedPhoto, setZoomedPhoto] = useState(null);
  const [activeClip, setActiveClip] = useState(null);

  // 24/7 CCTV Recordings Modal & Archive State
  const [showRecordingsModal, setShowRecordingsModal] = useState(false);
  const [recordingsList, setRecordingsList] = useState([]);
  const [recordingsLoading, setRecordingsLoading] = useState(false);
  const [activeVideoUrl, setActiveVideoUrl] = useState(null);
  const [recordingsTotalMb, setRecordingsTotalMb] = useState(0);

  const fetchRecordings = async () => {
    setRecordingsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/recordings`);
      if (res.ok) {
        const data = await res.json();
        setRecordingsList(data.recordings || []);
        setRecordingsTotalMb(data.total_size_mb || 0);
      }
    } catch (e) {
      console.error('Failed to fetch recordings', e);
    } finally {
      setRecordingsLoading(false);
    }
  };

  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const toastTimeoutRef = useRef(null);

  // Official Field Notification Toast
  const showToast = (msg) => {
    setToastMessage(msg);
    if (toastTimeoutRef.current) clearTimeout(toastTimeoutRef.current);
    toastTimeoutRef.current = setTimeout(() => {
      setToastMessage('');
    }, 3500);
  };

  // Subtle Audio Alert for Field Guard on Gate Crossing
  const playChime = () => {
    if (!audioEnabled) return;
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) return;
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(1320, ctx.currentTime + 0.12);

      gain.gain.setValueAtTime(0.2, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.35);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start();
      osc.stop(ctx.currentTime + 0.35);
    } catch (e) {}
  };

  // Official Authentication Handler
  const handleLogin = async (e, directUser, directPass) => {
    if (e) e.preventDefault();
    setLoginError('');
    setLoginLoading(true);
    const u = (directUser || loginForm.username || '').trim();
    const p = directPass || loginForm.password || '';

    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: p }),
      });

      if (res.ok) {
        const data = await res.json();
        setToken(data.access_token);
        setCurrentUser(data.user);
        localStorage.setItem('gate_token', data.access_token);
        localStorage.setItem('gate_user', JSON.stringify(data.user));
        showToast(`Welcome, ${data.user.username} (${data.user.role.toUpperCase()})`);
        return data.access_token;
      } else {
        const err = await res.json().catch(() => ({}));
        setLoginError(err.detail || 'Sign-in failed. Please verify credentials.');
      }
    } catch (err) {
      setLoginError('Could not reach authentication server. Please check connection.');
    } finally {
      setLoginLoading(false);
    }
    return null;
  };

  // Officer Sign-out
  const handleLogout = () => {
    setToken('');
    setCurrentUser(null);
    localStorage.removeItem('gate_token');
    localStorage.removeItem('gate_user');
    setLoginForm({ username: '', password: '' });
    showToast('Officer signed out successfully.');
  };

  // Office Staff Management API calls (Admin only)
  const fetchUsers = async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/users`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setUsersList(data);
      }
    } catch (e) {}
  };

  const handleCreateUser = async (e) => {
    e.preventDefault();
    setUserFormError('');
    if (!newUserForm.username || !newUserForm.password) {
      setUserFormError('Please enter both username and password.');
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/v1/users`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(newUserForm),
      });
      if (res.ok) {
        showToast(`Office account '${newUserForm.username}' created successfully.`);
        setNewUserForm({ username: '', password: '', role: 'reviewer' });
        fetchUsers();
      } else {
        const err = await res.json().catch(() => ({}));
        setUserFormError(err.detail || 'Could not create account.');
      }
    } catch (err) {
      setUserFormError('Network error while creating account.');
    }
  };

  // Ping Heartbeat
  const handleHeartbeatPing = async () => {
    try {
      const pingStart = performance.now();
      const res = await fetch(`${API_BASE}/api/v1/health/status`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      const pingMs = Math.round(performance.now() - pingStart);
      if (res.ok) {
        const data = await res.json();
        if (data.devices && data.devices.length > 0) {
          setHealth(data.devices[0]);
          setLatency(data.devices[0].online ? pingMs : null);
        }
        showToast(`Hardware telemetry synced (${pingMs}ms latency)`);
      }
    } catch (e) {
      showToast('Telemetry server currently unreachable.');
    }
  };

  // Robust Data Fetching with 401 token auto-refresh
  const fetchData = async (overrideToken) => {
    const activeToken = overrideToken || token;
    if (!activeToken) return;
    const headers = { Authorization: `Bearer ${activeToken}` };

    // 1. Stats
    try {
      const statsRes = await fetch(`${API_BASE}/api/v1/stats/today`, { headers });
      if (statsRes.status === 401) {
        handleLogout();
        return;
      } else if (statsRes.ok) {
        const statsData = await statsRes.json();
        setStats(statsData);
      }
    } catch (e) {}

    // 2. Gate Health & Real Latency Telemetry
    try {
      const pingStart = performance.now();
      const healthRes = await fetch(`${API_BASE}/api/v1/health/status`, { headers });
      const pingMs = Math.round(performance.now() - pingStart);
      if (healthRes.ok) {
        const hData = await healthRes.json();
        if (hData.devices && hData.devices.length > 0) {
          const dev = hData.devices[0];
          setHealth(dev);
          setLatency(dev.online ? pingMs : null);
        }
      } else {
        setLatency(null);
      }
    } catch (e) {
      setLatency(null);
    }

    // 3. Detections Register
    try {
      let url = `${API_BASE}/api/v1/detections?limit=100`;
      const detRes = await fetch(url, { headers });
      if (detRes.ok) {
        const detData = await detRes.json();
        const uniqueMap = new Map();
        for (const item of (detData.items || [])) {
          uniqueMap.set(item.id, item);
        }
        setDetections(Array.from(uniqueMap.values()));
      }
    } catch (e) {}
  };

  // Proactive check on mount
  useEffect(() => {
    if (token) {
      fetchData();
    }
  }, [token]);

  // Periodic Telemetry Sync Loop
  useEffect(() => {
    if (!token) return;
    const interval = setInterval(() => {
      fetchData();
    }, 4000);
    return () => clearInterval(interval);
  }, [token]);

  // Robust WebSocket Connection with Automatic Reconnection Loop
  useEffect(() => {
    if (!token) return;

    let isUnmounted = false;

    const connectWebSocket = () => {
      if (isUnmounted) return;
      const wsUrl = `${WS_BASE}/ws/live?token=${token}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isUnmounted) setWsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === 'detection.created') {
            playChime();
            const newDetection = { ...message.data, isNew: true };
            // Ensure multiple simultaneous vehicles are all appended without dropping
            setDetections((prev) => [newDetection, ...prev.filter((d) => d.id !== newDetection.id)]);
            setStats((prev) => ({
              ...prev,
              vehicles: prev.vehicles + 1,
              trucks: message.data.vehicle_type === 'truck' ? prev.trucks + 1 : prev.trucks,
              loaded: message.data.load_type !== 'empty' && message.data.load_type !== 'unknown' ? prev.loaded + 1 : prev.loaded,
              needs_review: message.data.status === 'needs_review' ? prev.needs_review + 1 : prev.needs_review,
            }));
          } else if (message.type === 'detection.updated') {
            setDetections((prev) =>
              prev.map((d) => (d.id === message.data.id ? { ...d, ...message.data } : d))
            );
          } else if (message.type === 'health.updated') {
            setHealth((prev) => ({ ...prev, ...message.data, online: true }));
          } else if (message.type === 'register.cleared') {
            setDetections([]);
            setStats({ vehicles: 0, trucks: 0, loaded: 0, needs_review: 0 });
          }
        } catch (err) {}
      };

      ws.onclose = (event) => {
        if (!isUnmounted) {
          setWsConnected(false);
          if (event.code === 1008) {
            handleLogout();
          } else {
            reconnectTimeoutRef.current = setTimeout(connectWebSocket, 3000);
          }
        }
      };

      ws.onerror = () => {
        if (!isUnmounted) setWsConnected(false);
      };
    };

    connectWebSocket();

    return () => {
      isUnmounted = true;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [token, audioEnabled]);

  // Simulate Crossing Action
  const handleSimulatePass = async () => {
    setIsSimulating(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/events/simulate`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const simulated = await res.json();
        showToast(`Gate pass verified: ${simulated.plate} (${simulated.vehicle_type})`);
        fetchData();
      } else {
        showToast('Simulation failed. Server error.');
      }
    } catch (e) {
      showToast('Could not reach simulation endpoint.');
    } finally {
      setIsSimulating(false);
    }
  };

  // Clear Register Action
  const handleClearRegister = async () => {
    if (!window.confirm('Clear all test detections and reset day counter?')) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/detections/clear-all`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        setDetections([]);
        setStats({ vehicles: 0, trucks: 0, loaded: 0, needs_review: 0 });
        showToast('Register cleared and counter reset.');
      }
    } catch (e) {
      alert('Could not clear register.');
    }
  };

  // Submit Correction
  const handleCorrectionSubmit = async (e) => {
    e.preventDefault();
    if (!editingDetection) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/detections/${editingDetection.id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(correctionForm),
      });
      if (res.ok) {
        const updated = await res.json();
        setDetections((prev) => prev.map((d) => (d.id === updated.id ? updated : d)));
        setEditingDetection(null);
        showToast(`Pass #${updated.day_serial} updated successfully`);
        fetchData();
      } else {
        const err = await res.json();
        alert(err.detail || 'Correction could not be saved.');
      }
    } catch (err) {
      alert('Network error while updating record.');
    }
  };

  // Open Video Clip
  const handleOpenClip = async (detection) => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/detections/${detection.id}/clip`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setActiveClip(data.clip_url);
      } else {
        alert('Video recording stream not available for this pass or tunnel inactive.');
      }
    } catch (e) {
      alert('Could not establish video connection.');
    }
  };

  // Export Daily Register CSV
  const handleExportCSV = () => {
    window.open(`${API_BASE}/api/v1/detections/export.csv`, '_blank');
  };

  // Helper to extract clean photo URL for plate, scene, or cargo
  const getPhotoUrl = (d, kind) => {
    if (!d || !d.thumbnails) return null;
    const raw = d.thumbnails[kind] || (kind === 'cargo' ? d.thumbnails['load_thumb'] : null);
    if (!raw) return null;
    return raw.startsWith('/') ? `${API_BASE}${raw}` : raw;
  };

  // Download all 3 high-res evidentiary photos as named official files
  const downloadEvidencePhotos = async (d) => {
    if (!d) return;
    const items = [
      { key: 'plate', label: '1_number_plate_crop' },
      { key: 'scene', label: '2_vehicle_front_overview' },
      { key: 'load_thumb', label: '3_vehicle_back_cargo' },
    ];
    let downloadedCount = 0;
    for (const item of items) {
      const url = getPhotoUrl(d, item.key);
      if (url) {
        downloadedCount++;
        const a = document.createElement('a');
        a.href = url;
        a.download = `Pass_${String(d.day_serial).padStart(3, '0')}_${d.plate || d.plate_raw}_${item.label}.jpg`;
        a.target = '_blank';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        await new Promise((r) => setTimeout(r, 200));
      }
    }
    if (downloadedCount > 0) {
      showToast(`Downloaded ${downloadedCount} evidence photos for Pass #${d.day_serial}`);
    } else {
      alert('No high-resolution evidence photos available to download for this pass.');
    }
  };

  // Direct 1-Click Pass Verification for Officers
  const handleQuickVerify = async (detectionId) => {
    if (!token || !currentUser) {
      showToast('Officer authentication required to verify passes');
      setShowLoginModal(true);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/v1/detections/${detectionId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ status: 'verified' }),
      });
      if (res.ok) {
        const updated = await res.json();
        setDetections((prev) => prev.map((d) => (d.id === updated.id ? updated : d)));
        if (activeDossier && activeDossier.id === updated.id) {
          setActiveDossier(updated);
        }
        showToast(`Pass #${updated.day_serial} verified & cleared`);
        fetchData();
      } else if (res.status === 401 || res.status === 403) {
        showToast('Officer session expired or unauthorized. Please sign in.');
        setShowLoginModal(true);
      } else {
        const err = await res.json();
        alert(err.detail || 'Could not verify pass. Officer login may be required.');
      }
    } catch (err) {
      alert('Network error while verifying record.');
    }
  };

  // --------------------------------------------------------------------------
  // PAGE 1: LIVE 24-HOUR FILTERING & AGGREGATION
  // --------------------------------------------------------------------------
  const now = new Date();
  const live24hDetections = detections.filter((d) => {
    const t = parseUtcDate(d.captured_at).getTime();
    const diff = now.getTime() - t;
    // Strictly within last 24 hours (86,400,000 ms) with 10-minute future clock tolerance
    return diff <= 86400000 && diff >= -600000;
  });

  const liveStats = {
    vehicles: live24hDetections.length,
    trucks: live24hDetections.filter((d) => d.vehicle_type === 'truck').length,
    loaded: live24hDetections.filter(
      (d) => d.load_type && d.load_type !== 'empty' && d.load_type !== 'unknown'
    ).length,
    needs_review: live24hDetections.filter((d) => d.status === 'needs_review').length,
  };

  const filteredLiveDetections = live24hDetections.filter((d) => {
    if (searchPlate && !(d.plate || d.plate_raw || '').toLowerCase().includes(searchPlate.toLowerCase())) {
      return false;
    }
    if (filterVehicleType && d.vehicle_type !== filterVehicleType) return false;
    if (filterLoadType && d.load_type !== filterLoadType) return false;
    if (filterStatus && d.status !== filterStatus) return false;
    return true;
  });

  // --------------------------------------------------------------------------
  // PAGE 2: MULTI-DAY & FOOTAGE ARCHIVES (User requested ScheduleDate & Pagination5)
  // --------------------------------------------------------------------------
  const applyArchivePreset = (presetId) => {
    setArchivePreset(presetId);
    setArchivePage(1);
    const today = new Date();
    today.setHours(23, 59, 59, 999);
    const startOfToday = new Date();
    startOfToday.setHours(0, 0, 0, 0);

    let newStart = new Date(startOfToday);
    let newEnd = new Date(today);

    if (presetId === 'today') {
      newStart = startOfToday;
    } else if (presetId === 'yesterday') {
      newStart = new Date(startOfToday.getTime() - 86400000);
      newEnd = new Date(startOfToday.getTime() - 1);
    } else if (presetId === '7d') {
      newStart = new Date(startOfToday.getTime() - 6 * 86400000);
    } else if (presetId === '30d') {
      newStart = new Date(startOfToday.getTime() - 29 * 86400000);
    } else if (presetId === '365d') {
      newStart = new Date(startOfToday.getTime() - 364 * 86400000);
    } else if (presetId === 'wtd') {
      const dayOfWeek = (today.getDay() + 6) % 7;
      newStart = new Date(startOfToday.getTime() - dayOfWeek * 86400000);
    } else if (presetId === 'mtd') {
      newStart = new Date(today.getFullYear(), today.getMonth(), 1);
    } else if (presetId === 'ytd') {
      newStart = new Date(today.getFullYear(), 0, 1);
    } else if (presetId === 'custom') {
      setShowScheduleModal(true);
      return;
    }
    setArchiveRange({ start: newStart, end: newEnd });
  };

  const archiveFilteredDetections = detections.filter((d) => {
    const t = parseUtcDate(d.captured_at).getTime();
    const startMs = archiveRange.start ? new Date(archiveRange.start).setHours(0, 0, 0, 0) : 0;
    const endMs = archiveRange.end ? new Date(archiveRange.end).setHours(23, 59, 59, 999) : Infinity;
    const withinDate = t >= startMs && t <= endMs;
    if (!withinDate) return false;

    if (archiveSearchPlate && !(d.plate || d.plate_raw || '').toLowerCase().includes(archiveSearchPlate.toLowerCase())) {
      return false;
    }
    if (archiveVehicleType && d.vehicle_type !== archiveVehicleType) return false;
    if (archiveLoadType && d.load_type !== archiveLoadType) return false;
    if (archiveStatus && d.status !== archiveStatus) return false;
    return true;
  });

  const archiveTotals = {
    total: archiveFilteredDetections.length,
    trucks: archiveFilteredDetections.filter((d) => d.vehicle_type === 'truck').length,
    regulatedCargo: archiveFilteredDetections.filter((d) =>
      ['timber_logs', 'bamboo', 'sand', 'stone_gravel'].includes(d.load_type)
    ).length,
    needsReview: archiveFilteredDetections.filter((d) => d.status === 'needs_review').length,
    stoppedPasses: archiveFilteredDetections.filter((d) => d.speed_kph === 0).length,
  };

  const totalArchivePages = Math.max(1, Math.ceil(archiveFilteredDetections.length / archivePageSize));
  const paginatedArchive = archiveFilteredDetections.slice(
    (archivePage - 1) * archivePageSize,
    archivePage * archivePageSize
  );

  const formatArchiveRangeLabel = () => {
    if (!archiveRange.start || !archiveRange.end) return 'Select Date Range';
    const opts = { day: 'numeric', month: 'short', year: 'numeric' };
    return `${archiveRange.start.toLocaleDateString('en-IN', opts)} — ${archiveRange.end.toLocaleDateString('en-IN', opts)}`;
  };

  const handleExportArchiveCSV = () => {
    if (archiveFilteredDetections.length === 0) {
      alert('No records to export in the selected date range.');
      return;
    }
    const headers = [
      'Pass #',
      'Plate Number',
      'Vehicle Class',
      'Color',
      'Speed (km/h)',
      'Direction',
      'Cargo Type',
      'Transit Time IST',
      'Status',
      'ANPR Confidence',
    ];
    const rows = archiveFilteredDetections.map((d) => [
      d.day_serial || d.id,
      d.plate || d.plate_raw || 'UNKNOWN',
      d.vehicle_type || 'Unknown',
      d.vehicle_color || 'Unknown',
      d.speed_kph != null ? d.speed_kph : 'N/A',
      d.direction || 'N/A',
      d.load_type || 'N/A',
      formatTransitTime(d.captured_at),
      d.status,
      `${Math.round((d.plate_conf || 1) * 100)}%`,
    ]);
    const csvContent =
      'data:text/csv;charset=utf-8,' +
      [headers.join(','), ...rows.map((e) => e.map((v) => `"${v}"`).join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute(
      'download',
      `AVGMS_Archive_${archiveRange.start.toISOString().slice(0, 10)}_to_${archiveRange.end.toISOString().slice(0, 10)}.csv`
    );
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast(`Exported ${archiveFilteredDetections.length} archive records to CSV`);
  };

  // Dedicated Lock Screen: Authorized Office Personnel Portal
  if (!token) {
    return (
      <div className="gov-login-portal-backdrop">
        <div className="gov-login-portal-card">
          <div className="gov-login-portal-header">
            <div className="gov-login-crest">
              <Shield size={32} color="#FFFFFF" />
            </div>
            <span className="gov-login-dept">FOREST &amp; WILDLIFE SURVEILLANCE COMMAND</span>
            <h1 className="gov-login-title">ANPR Gate Security Portal</h1>
            <p className="gov-login-subtitle">Restricted Access • Authorized Office Personnel Only</p>
          </div>

          <form onSubmit={handleLogin} className="gov-login-portal-form">
            {loginError && (
              <div className="gov-login-error-alert" role="alert">
                <AlertTriangle size={16} />
                <span>{loginError}</span>
              </div>
            )}

            <div className="gov-login-field">
              <label htmlFor="login-username">Officer / Operator Username</label>
              <div className="gov-login-input-wrap">
                <UserCheck size={16} className="gov-login-input-icon" />
                <input
                  id="login-username"
                  type="text"
                  placeholder="Enter official username (e.g. admin)"
                  value={loginForm.username}
                  onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })}
                  required
                  autoFocus
                />
              </div>
            </div>

            <div className="gov-login-field">
              <label htmlFor="login-password">Secret Passkey / Password</label>
              <div className="gov-login-input-wrap">
                <Lock size={16} className="gov-login-input-icon" />
                <input
                  id="login-password"
                  type="password"
                  placeholder="Enter password"
                  value={loginForm.password}
                  onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })}
                  required
                />
              </div>
            </div>

            <button type="submit" className="gov-login-submit-btn" disabled={loginLoading}>
              {loginLoading ? (
                <>
                  <RefreshCw size={16} className="spin" />
                  <span>Verifying Credentials...</span>
                </>
              ) : (
                <>
                  <LogIn size={16} />
                  <span>Sign In to Dashboard</span>
                </>
              )}
            </button>
          </form>

          <div className="gov-credentials-hint-box">
            <div className="gov-credentials-hint-title">
              <ShieldAlert size={13} color="var(--forest-green-700)" />
              <span>Office Staff Roles &amp; Passkeys</span>
            </div>
            <div className="gov-credentials-grid">
              <span>Admin:</span>
              <span>admin / AdminGatePassword2026!</span>
              <span>Officer:</span>
              <span>reviewer / ReviewerPass2026!</span>
              <span>Monitor:</span>
              <span>viewer / ViewerPass2026!</span>
            </div>
          </div>

          <div className="gov-login-footer">
            <div className="gov-security-badge">
              <ShieldAlert size={14} />
              <span>Zero-Trust Gate Monitoring System</span>
            </div>
            <p className="gov-login-notice">
              All sign-in attempts are timestamped and cryptographically recorded. Unauthorized access is strictly restricted to designated checkpost staff.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="gov-app-shell">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="gov-toast">
          <Check size={16} color="var(--forest-green-400)" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Sleek Professional Top Bar (All Hardware Status moved here, Unwanted text removed) */}
      <header className="gov-header">
        {/* Left: Clean Brand Logo + Compact Title */}
        <div className="gov-brand-container">
          <div className="gov-crest-box">
            <Shield size={18} color="#FFFFFF" />
          </div>
          <div className="gov-title-stack">
            <span className="gov-system-title">ANPR Gate Monitor</span>
            <span className="gov-checkpoint-meta">Checkpost 01</span>
          </div>
        </div>

        {/* Center-Left: Small, Sleek Hardware & Telemetry Badges */}
        <div className="topbar-telemetry-cluster">
          <div
            className={`topbar-telemetry-pill ${!wsConnected ? 'offline' : health.online ? 'ok' : 'offline'}`}
            onClick={handleHeartbeatPing}
            style={{ cursor: 'pointer' }}
            title={health.online ? 'Edge GateBox Online (Click to re-ping)' : 'Click to connect Edge GateBox'}
          >
            <span className={`beacon-dot ${health.online ? 'pulse' : ''}`} />
            <span>Edge: {health.online ? 'Online' : 'Offline'}</span>
          </div>

          <div className={`topbar-telemetry-pill ${health.online && health.camera_a_ok ? 'ok' : 'offline'}`}>
            <Camera size={12} />
            <span>Cam A: {health.online && health.camera_a_ok ? 'Active' : 'Offline'}</span>
          </div>

          <div className={`topbar-telemetry-pill ${health.online && health.camera_b_ok ? 'ok' : 'offline'}`}>
            <Camera size={12} />
            <span>Cam B: {health.online && health.camera_b_ok ? 'Active' : 'Offline'}</span>
          </div>

          <div className="topbar-telemetry-pill neutral">
            <HardDrive size={12} />
            <span>{health.online ? `${health.disk_used_pct || 0}% Disk` : '--'}</span>
          </div>

          <div className="topbar-telemetry-pill neutral">
            <Activity size={12} />
            <span>{latency !== null ? `${latency}ms` : '--'}</span>
          </div>

          <button
            type="button"
            className="btn-topbar-sync"
            onClick={handleHeartbeatPing}
            title="Sync Hardware Telemetry"
          >
            <RefreshCw size={11} />
          </button>
        </div>

        {/* Center-Right: Navigation Tabs */}
        <nav className="gov-nav-tabs" aria-label="Dashboard Views">
          <button
            type="button"
            className={`gov-nav-tab ${activeTab === 'live_24h' ? 'active' : ''}`}
            onClick={() => setActiveTab('live_24h')}
          >
            <span className="live-pulse-dot" />
            <span>Live (24h)</span>
            <span className="gov-nav-badge">{live24hDetections.length}</span>
          </button>
          <button
            type="button"
            className={`gov-nav-tab ${activeTab === 'archives' ? 'active' : ''}`}
            onClick={() => setActiveTab('archives')}
          >
            <Calendar size={13} />
            <span>Archives</span>
            <span className="gov-nav-badge">{detections.length}</span>
          </button>
        </nav>

        {/* Right: Actions & Officer Profile */}
        <div className="gov-header-controls">
          <button
            className="btn-gov-icon"
            title={audioEnabled ? 'Audio alert active' : 'Audio alert muted'}
            onClick={() => setAudioEnabled(!audioEnabled)}
          >
            {audioEnabled ? <Volume2 size={15} color="var(--forest-green-700)" /> : <VolumeX size={15} color="var(--text-muted)" />}
          </button>

          <button
            className="btn-gov simulate"
            disabled={isSimulating}
            onClick={handleSimulatePass}
            title="Test vehicle gate crossing detection"
          >
            <PlusCircle size={13} />
            {isSimulating ? 'Logging...' : '+ Test Pass'}
          </button>

          {currentUser?.role === 'admin' && (
            <button
              type="button"
              className="btn-gov"
              style={{ fontSize: '0.78rem', padding: '0.35rem 0.65rem' }}
              onClick={() => {
                setShowUsersModal(true);
                fetchUsers();
              }}
              title="Manage Office Staff Logins & Passwords"
            >
              <Users size={13} />
              <span>Staff Accounts</span>
            </button>
          )}

          {currentUser ? (
            <div className="gov-operator-tag">
              <div className="operator-shield-avatar">
                {currentUser.username ? currentUser.username.slice(0, 2).toUpperCase() : 'FD'}
              </div>
              <span className="operator-username">{currentUser.username} ({currentUser.role})</span>
              <button
                className="btn-gov-icon"
                style={{ marginLeft: '0.2rem', padding: '0.2rem' }}
                title="Sign out of portal"
                onClick={handleLogout}
              >
                <LogOut size={12} />
              </button>
            </div>
          ) : (
            <button className="btn-gov primary" onClick={handleLogout}>
              <LogIn size={13} /> Sign In
            </button>
          )}
        </div>
      </header>

      {/* ====================================================================
          PAGE 1: LIVE 24-HOUR MONITORING VIEW
          ==================================================================== */}
      {activeTab === 'live_24h' && (
        <>
          {/* 4 Core Government Operational KPI Metrics */}
          <section className="gov-kpi-row">
            <div
              className={`gov-kpi-card ${!filterStatus && !filterVehicleType && !filterLoadType && !searchPlate ? 'active-kpi' : ''}`}
              onClick={() => {
                setFilterStatus('');
                setFilterVehicleType('');
                setFilterLoadType('');
                setSearchPlate('');
              }}
              title="Click to view all daily vehicle passes"
            >
              <div className="gov-kpi-info">
                <span className="gov-kpi-label">Today's Ingress (24h)</span>
                <span className="gov-kpi-number">{liveStats.vehicles}</span>
                <span className="gov-kpi-footnote">
                  <Activity size={12} color="var(--forest-green-700)" /> Total vehicles logged in 24h
                </span>
              </div>
              <div className="gov-kpi-icon-cell" style={{ background: 'var(--forest-green-bg)', color: 'var(--forest-green-700)' }}>
                <Car size={20} />
              </div>
            </div>

            <div
              className={`gov-kpi-card ${filterVehicleType === 'truck' ? 'active-kpi' : ''}`}
              onClick={() => setFilterVehicleType(filterVehicleType === 'truck' ? '' : 'truck')}
              title="Click to filter commercial heavy trucks"
            >
              <div className="gov-kpi-info">
                <span className="gov-kpi-label">Commercial Freight</span>
                <span className="gov-kpi-number">{liveStats.trucks}</span>
                <span className="gov-kpi-footnote">
                  <Truck size={12} color="var(--gov-navy-400)" /> Heavy transport vehicles
                </span>
              </div>
              <div className="gov-kpi-icon-cell" style={{ background: 'var(--gov-navy-bg)', color: 'var(--gov-navy-400)' }}>
                <Truck size={20} />
              </div>
            </div>

            <div
              className={`gov-kpi-card ${filterLoadType === 'timber_logs' ? 'active-kpi' : ''}`}
              onClick={() => setFilterLoadType(filterLoadType === 'timber_logs' ? '' : 'timber_logs')}
              title="Click to filter timber & regulated cargo"
            >
              <div className="gov-kpi-info">
                <span className="gov-kpi-label">Permitted Cargo</span>
                <span className="gov-kpi-number">{liveStats.loaded}</span>
                <span className="gov-kpi-footnote">
                  <Layers size={12} color="var(--forest-green-700)" /> Timber, bamboo, materials
                </span>
              </div>
              <div className="gov-kpi-icon-cell" style={{ background: 'var(--forest-green-bg)', color: 'var(--forest-green-700)' }}>
                <Layers size={20} />
              </div>
            </div>

            <div
              className={`gov-kpi-card ${liveStats.needs_review > 0 ? 'kpi-warning' : ''} ${filterStatus === 'needs_review' ? 'active-kpi' : ''}`}
              onClick={() => setFilterStatus(filterStatus === 'needs_review' ? '' : 'needs_review')}
              title="Click to view passes flagged for physical officer inspection"
            >
              <div className="gov-kpi-info">
                <span className="gov-kpi-label">Pending Inspection</span>
                <span className="gov-kpi-number" style={{ color: liveStats.needs_review > 0 ? 'var(--gov-gold-400)' : '#0F172A' }}>
                  {liveStats.needs_review}
                </span>
                <span className="gov-kpi-footnote">
                  <AlertTriangle size={12} color="var(--gov-gold-400)" /> Discrepancies / manual check
                </span>
              </div>
              <div className="gov-kpi-icon-cell" style={{ background: 'var(--gov-gold-bg)', color: 'var(--gov-gold-400)' }}>
                <AlertTriangle size={20} />
              </div>
            </div>
          </section>

          {/* Operational Filter & Search Toolbar */}
          <section className="gov-toolbar">
            <div className="gov-search-input-box">
              <Search size={15} className="gov-search-icon" />
              <input
                type="text"
                className="gov-search-input"
                placeholder="Search vehicle plate (e.g. CG07, KA05, MH12)..."
                value={searchPlate}
                onChange={(e) => setSearchPlate(e.target.value)}
              />
              {searchPlate && (
                <button
                  className="btn-gov-icon"
                  style={{ position: 'absolute', right: '0.4rem', padding: '0.2rem', background: 'transparent', border: 'none' }}
                  title="Clear vehicle history filter"
                  onClick={() => setSearchPlate('')}
                >
                  <X size={14} color="var(--text-muted)" />
                </button>
              )}
            </div>

            <div className="gov-toolbar-filters">
              <select
                className="gov-select-control"
                value={filterVehicleType}
                onChange={(e) => setFilterVehicleType(e.target.value)}
              >
                <option value="">All Vehicle Classes</option>
                <option value="motorcycle">Two-Wheeler (Bike / Scooty)</option>
                <option value="truck">Heavy Truck</option>
                <option value="pickup">Pickup</option>
                <option value="van">Van</option>
                <option value="car">Car / SUV</option>
                <option value="bus">Bus</option>
              </select>

              <select
                className="gov-select-control"
                value={filterLoadType}
                onChange={(e) => setFilterLoadType(e.target.value)}
              >
                <option value="">All Cargo Categories</option>
                <option value="timber_logs">Timber Logs</option>
                <option value="bamboo">Bamboo</option>
                <option value="sand">Sand / Mineral</option>
                <option value="stone_gravel">Stone / Gravel</option>
                <option value="bags">Bags / Agricultural</option>
                <option value="empty">Empty Cargo Bed</option>
                <option value="covered">Covered / Tarpaulin</option>
              </select>

              <select
                className="gov-select-control"
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value)}
              >
                <option value="">All Clearance Statuses ({liveStats.vehicles})</option>
                <option value="verified">Verified Clearance ({Math.max(0, liveStats.vehicles - liveStats.needs_review)})</option>
                <option value="needs_review">Inspection Required ({liveStats.needs_review})</option>
                <option value="corrected">Corrected by Officer</option>
              </select>

              {/* View Mode Switcher */}
              <div className="gov-view-switch">
                <button
                  className={`gov-view-switch-btn ${viewMode === 'table' ? 'active' : ''}`}
                  onClick={() => setViewMode('table')}
                  title="Official Register (Table View)"
                >
                  <List size={14} /> Register
                </button>
                <button
                  className={`gov-view-switch-btn ${viewMode === 'cards' ? 'active' : ''}`}
                  onClick={() => setViewMode('cards')}
                  title="Card Inspection View"
                >
                  <LayoutGrid size={14} /> Cards
                </button>
              </div>

              {currentUser && (currentUser.role === 'admin' || currentUser.role === 'reviewer') && (
                <>
                  <button className="btn-gov" onClick={handleExportCSV} title="Download official daily gate register CSV">
                    <Download size={13} /> Export Register
                  </button>
                  <button
                    className="btn-gov"
                    style={{ borderColor: '#FECACA', color: '#DC2626' }}
                    onClick={() => {
                      setShowRecordingsModal(true);
                      fetchRecordings();
                    }}
                    title="Browse and play 24/7 continuous CCTV video recordings on disk"
                  >
                    <Video size={13} /> 24/7 CCTV Recordings
                  </button>
                  <button
                    className="btn-gov"
                    style={{ borderColor: '#FECACA', color: '#DC2626' }}
                    onClick={handleClearRegister}
                    title="Clear all test detection records and reset counter"
                  >
                    <Trash2 size={13} /> Reset Test Data
                  </button>
                </>
              )}
            </div>
          </section>

          {/* Active Filter Indicators Bar */}
          {(searchPlate || filterVehicleType || filterLoadType || filterStatus) && (
            <div className="gov-active-filters-bar">
              <div className="active-filters-cluster">
                <span className="active-filter-label">
                  <Filter size={13} color="var(--gov-navy-400)" /> Active Filters:
                </span>
                {searchPlate && (
                  <span className="active-filter-chip">
                    <span>Plate: <strong>{searchPlate}</strong></span>
                    <button
                      className="active-filter-chip-remove"
                      onClick={() => setSearchPlate('')}
                      title="Remove plate filter"
                    >
                      <X size={12} />
                    </button>
                  </span>
                )}
                {filterVehicleType && (
                  <span className="active-filter-chip">
                    <span>Vehicle: <strong style={{ textTransform: 'capitalize' }}>{filterVehicleType === 'motorcycle' ? 'Two-Wheeler' : filterVehicleType}</strong></span>
                    <button
                      className="active-filter-chip-remove"
                      onClick={() => setFilterVehicleType('')}
                      title="Remove vehicle filter"
                    >
                      <X size={12} />
                    </button>
                  </span>
                )}
                {filterLoadType && (
                  <span className="active-filter-chip">
                    <span>Cargo: <strong style={{ textTransform: 'capitalize' }}>{filterLoadType.replace(/_/g, ' ')}</strong></span>
                    <button
                      className="active-filter-chip-remove"
                      onClick={() => setFilterLoadType('')}
                      title="Remove cargo filter"
                    >
                      <X size={12} />
                    </button>
                  </span>
                )}
                {filterStatus && (
                  <span className="active-filter-chip">
                    <span>Status: <strong style={{ textTransform: 'capitalize' }}>{filterStatus.replace(/_/g, ' ')}</strong></span>
                    <button
                      className="active-filter-chip-remove"
                      onClick={() => setFilterStatus('')}
                      title="Remove status filter"
                    >
                      <X size={12} />
                    </button>
                  </span>
                )}
              </div>
              <button
                className="btn-clear-all-filters"
                onClick={() => {
                  setSearchPlate('');
                  setFilterVehicleType('');
                  setFilterLoadType('');
                  setFilterStatus('');
                }}
                title="Reset and clear all filters"
              >
                Reset All Filters
              </button>
            </div>
          )}

          {/* Main Stream: Live Gate Ingress Register (24 Hours Only) */}
          <main className="gov-register-container">
            {filteredLiveDetections.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '3.5rem 1.5rem', background: '#FFFFFF' }}>
                <Camera size={36} color="var(--text-muted)" style={{ margin: '0 auto 0.75rem' }} />
                {searchPlate || filterVehicleType || filterLoadType || filterStatus ? (
                  <div>
                    <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#0F172A' }}>
                      No 24-Hour Passes Match Active Filters
                    </h3>
                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.25rem' }}>
                      Try clearing your search query or vehicle class filters.
                    </p>
                  </div>
                ) : (
                  <div>
                    <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#0F172A' }}>
                      No Gate Crossings Recorded in the Last 24 Hours
                    </h3>
                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.25rem' }}>
                      Vehicles crossing the gate will automatically appear here with ANPR license plate reads and cargo verification.
                    </p>
                    <div style={{ marginTop: '1rem' }}>
                      <button className="btn-gov simulate" onClick={handleSimulatePass}>
                        <PlusCircle size={14} /> Test Gate Pass Now
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ) : viewMode === 'table' ? (
              <div className="gov-register-table-wrapper">
                <table className="gov-register-table">
                  <thead>
                    <tr>
                      <th>Pass #</th>
                      <th>Registration (Plate Photo & HSRP)</th>
                      <th>Vehicle Class & Speed</th>
                      <th>Declared Cargo</th>
                      <th>Transit Time</th>
                      <th>Clearance</th>
                      <th>Evidence (Front / Back)</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredLiveDetections.map((d, idx) => (
                      <tr key={`${d.id || idx}-${idx}`} className={d.isNew ? 'row-arrival' : ''}>
                        <td>
                          <span className="serial-stamp">#{String(d.day_serial || idx + 1).padStart(3, '0')}</span>
                        </td>
                        {/* Registration: Camera Plate Photo + HSRP Plate Component */}
                        <td>
                          <div className="plate-identity-cell">
                            {getPhotoUrl(d, 'plate') ? (
                              <div
                                className="plate-crop-thumb-box"
                                onClick={() => {
                                  const u = getPhotoUrl(d, 'plate');
                                  if (u) setZoomedPhoto({ url: u, title: `Plate Photo — Pass #${d.day_serial || d.id}` });
                                }}
                                title="Actual camera plate photo — Click to zoom"
                              >
                                <img
                                  src={getPhotoUrl(d, 'plate')}
                                  alt="Plate Crop"
                                  className="plate-crop-thumb-img"
                                />
                                <div className="plate-zoom-badge">
                                  <Maximize2 size={9} />
                                </div>
                              </div>
                            ) : (
                              <div className="plate-crop-placeholder" title="No optical plate photo available">
                                <Camera size={13} />
                              </div>
                            )}

                            <div className="plate-text-stack">
                              <HsrpPlate plate={d.plate} rawPlate={d.plate_raw} isValid={d.plate_valid} />
                              <div className="plate-sub-meta">
                                <span className="plate-conf-stat">
                                  {Math.round((d.plate_conf || 1) * 100)}% Conf
                                </span>
                                <button
                                  type="button"
                                  className="btn-history-filter"
                                  title={`Filter crossing history for ${d.plate || d.plate_raw}`}
                                  onClick={() => setSearchPlate(d.plate || d.plate_raw)}
                                >
                                  <Clock size={10} /> History
                                </button>
                              </div>
                            </div>
                          </div>
                        </td>

                        {/* Vehicle Class & Speed */}
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontWeight: 700 }}>
                            {d.vehicle_type === 'motorcycle' && <Bike size={14} color="var(--forest-green-700)" />}
                            {d.vehicle_type === 'truck' && <Truck size={14} color="var(--gov-navy-400)" />}
                            {d.vehicle_type === 'car' && <Car size={14} color="var(--text-muted)" />}
                            <span>
                              {d.vehicle_make
                                ? `${d.vehicle_make} ${d.vehicle_model || ''}`
                                : d.vehicle_type === 'motorcycle'
                                ? 'Two-Wheeler'
                                : d.vehicle_type}
                            </span>
                          </div>
                          <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', display: 'flex', gap: '0.45rem', alignItems: 'center', marginTop: '2px' }}>
                            {d.vehicle_color && <span style={{ textTransform: 'capitalize' }}>🎨 {d.vehicle_color}</span>}
                            {d.speed_kph != null ? (
                              d.speed_kph === 0 ? (
                                <span className="speed-pill stopped">🛑 0.0 km/h (Stopped at Gate)</span>
                              ) : (
                                <span className="speed-pill moving">⚡ {d.speed_kph} km/h {d.direction && d.direction !== 'Stationary (Gate)' ? `(${d.direction})` : ''}</span>
                              )
                            ) : null}
                          </div>
                        </td>

                        {/* Declared Cargo (Properly categorized without fake timber) */}
                        <td>
                          {['motorcycle', 'scooter', 'two_wheeler', 'bicycle', 'car'].includes((d.vehicle_type || '').toLowerCase()) ? (
                            <span className="cargo-passenger-badge">
                              Passenger (No Cargo)
                            </span>
                          ) : (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                              <span className="cargo-freight-badge">
                                {d.load_type ? d.load_type.replace(/_/g, ' ') : 'N/A'}
                              </span>
                              <span style={{ fontSize: '0.725rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                                ({Math.round(d.load_conf * 100)}%)
                              </span>
                            </div>
                          )}
                        </td>

                        <td style={{ whiteSpace: 'nowrap' }}>
                          <div style={{ fontWeight: 600 }}>{formatTransitTime(d.captured_at)}</div>
                          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{formatTimeAgo(d.captured_at)}</div>
                        </td>

                        <td>
                          <span className={`clearance-badge ${d.status === 'verified' ? 'verified' : d.status === 'needs_review' ? 'inspection' : 'corrected'}`}>
                            {d.status === 'verified' && <CheckCircle2 size={12} />}
                            {d.status === 'needs_review' && <AlertTriangle size={12} />}
                            {d.status.replace(/_/g, ' ')}
                          </span>
                        </td>

                        {/* Evidence Dual Thumbs: Front and Back Photographs */}
                        <td>
                          <div className="evidence-dual-thumbs">
                            {/* Front Photo */}
                            {getPhotoUrl(d, 'scene') ? (
                              <div
                                className="evidence-thumb-card"
                                onClick={() => {
                                  const u = getPhotoUrl(d, 'scene');
                                  if (u) setZoomedPhoto({ url: u, title: `Front Vehicle Photo — Pass #${d.day_serial || d.id}` });
                                }}
                                title="Front Vehicle Gate Perspective — Click to zoom"
                              >
                                <div className="evidence-thumb-img-wrapper">
                                  <img src={getPhotoUrl(d, 'scene')} alt="Front View" />
                                </div>
                                <span className="evidence-thumb-tag">Front</span>
                              </div>
                            ) : null}

                            {/* Back Photo / Cargo Bed */}
                            {getPhotoUrl(d, 'load_thumb') || getPhotoUrl(d, 'scene') ? (
                              <div
                                className="evidence-thumb-card"
                                onClick={() => {
                                  const u = getPhotoUrl(d, 'load_thumb') || getPhotoUrl(d, 'scene');
                                  if (u) setZoomedPhoto({ url: u, title: `Rear Vehicle / Cargo Photo — Pass #${d.day_serial || d.id}` });
                                }}
                                title="Rear Departure / Cargo Perspective — Click to zoom"
                              >
                                <div className="evidence-thumb-img-wrapper">
                                  <img src={getPhotoUrl(d, 'load_thumb') || getPhotoUrl(d, 'scene')} alt="Rear View" />
                                </div>
                                <span className="evidence-thumb-tag">Back</span>
                              </div>
                            ) : null}

                            {(!d.thumbnails || Object.keys(d.thumbnails).length === 0) && (
                              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>No photos</span>
                            )}
                          </div>
                        </td>

                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                            <button
                              className="btn-gov-icon"
                              title="Open 3-Photo Transit Evidence Dossier"
                              onClick={() => setActiveDossier(d)}
                              style={{ color: 'var(--forest-green-700)' }}
                            >
                              <FileText size={13} />
                            </button>
                            <button className="btn-gov-icon" title="View gate video clip" onClick={() => handleOpenClip(d)}>
                              <Video size={13} />
                            </button>
                            {d.status !== 'verified' && (
                              <button
                                className="btn-gov-icon"
                                title={currentUser ? '1-Click Verify Clearance' : 'Sign in to verify clearance'}
                                style={{ color: 'var(--forest-green-700)' }}
                                onClick={() => handleQuickVerify(d.id)}
                              >
                                <CheckCircle2 size={13} />
                              </button>
                            )}
                            {currentUser && (currentUser.role === 'reviewer' || currentUser.role === 'admin') && (
                              <button
                                className="btn-gov-icon"
                                title="Inspect & correct pass"
                                onClick={() => {
                                  setEditingDetection(d);
                                  setCorrectionForm({
                                    plate: d.plate || d.plate_raw,
                                    vehicle_type: d.vehicle_type,
                                    load_type: d.load_type,
                                  });
                                }}
                              >
                                <Edit3 size={13} />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              /* Cards View */
              <div className="gov-cards-grid">
                {filteredLiveDetections.map((d, idx) => (
                  <article key={`${d.id || idx}-${idx}`} className="gov-card-item">
                    <div className="gov-card-media-box">
                      {getPhotoUrl(d, 'scene') ? (
                        <img src={getPhotoUrl(d, 'scene')} alt="Vehicle Crop" />
                      ) : (
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#94A3B8' }}>
                          <Camera size={24} />
                        </div>
                      )}
                    </div>
                    <div className="gov-card-content">
                      <div className="gov-card-header">
                        <span className="serial-stamp">#{String(d.day_serial || idx + 1).padStart(3, '0')}</span>
                        <span className={`clearance-badge ${d.status === 'verified' ? 'verified' : d.status === 'needs_review' ? 'inspection' : 'corrected'}`}>
                          {d.status.replace(/_/g, ' ')}
                        </span>
                      </div>
                      <div className="plate-identity-cell" style={{ margin: '0.4rem 0' }}>
                        {getPhotoUrl(d, 'plate') && (
                          <div className="plate-crop-thumb-box" onClick={() => setActiveDossier(d)}>
                            <img src={getPhotoUrl(d, 'plate')} alt="Plate Crop" className="plate-crop-thumb-img" />
                          </div>
                        )}
                        <HsrpPlate plate={d.plate} rawPlate={d.plate_raw} isValid={d.plate_valid} />
                      </div>
                      <div className="gov-card-details-grid">
                        <div className="gov-card-detail-item">
                          <span>Class & Color</span>
                          <span>{d.vehicle_type} ({d.vehicle_color || 'N/A'})</span>
                        </div>
                        <div className="gov-card-detail-item">
                          <span>Transit Time</span>
                          <span>{formatTransitTime(d.captured_at)}</span>
                        </div>
                        <div className="gov-card-detail-item">
                          <span>Speed</span>
                          <span>{d.speed_kph === 0 ? '0.0 km/h (Stopped)' : `${d.speed_kph || 0} km/h`}</span>
                        </div>
                        <div className="gov-card-detail-item">
                          <span>Cargo Status</span>
                          <span>{['motorcycle', 'car'].includes(d.vehicle_type) ? 'Passenger (N/A)' : d.load_type ? d.load_type.replace(/_/g, ' ') : 'N/A'}</span>
                        </div>
                      </div>
                      <div className="gov-card-footer">
                        <button className="btn-gov" onClick={() => setActiveDossier(d)}>
                          <FileText size={12} /> View Dossier
                        </button>
                        {d.status !== 'verified' && (
                          <button className="btn-gov primary" onClick={() => handleQuickVerify(d.id)}>
                            <CheckCircle2 size={12} /> Verify
                          </button>
                        )}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </main>
        </>
      )}

      {/* ====================================================================
          PAGE 2: FOOTAGE & DATE ARCHIVES (Second Page with ScheduleDate & Pagination5)
          ==================================================================== */}
      {activeTab === 'archives' && (
        <div className="archive-view-shell">
          {/* Archive Header Banner with Date Range Trigger */}
          <section className="archive-header-banner">
            <div className="archive-title-stack">
              <h2 className="archive-main-title">
                Surveillance Footage & Audit Archives
              </h2>
              <p className="archive-subtext">
                Filter, review, and inspect multi-day gate surveillance records, CCTV video clips, and ANPR evidentiary dossiers across custom date windows.
              </p>
            </div>

            <div className="archive-date-trigger-bar">
              <div className="archive-active-range-pill">
                <Calendar size={14} color="var(--forest-green-700)" />
                <span>{formatArchiveRangeLabel()}</span>
              </div>
              <button
                type="button"
                className="btn-gov primary"
                onClick={() => setShowScheduleModal(true)}
              >
                <CalendarDays size={14} /> Change Date Range / Presets
              </button>
            </div>
          </section>

          {/* Quick Date Presets Strip */}
          <section className="archive-presets-strip">
            <span style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
              Quick Presets:
            </span>
            {[
              { label: 'Today', id: 'today' },
              { label: 'Yesterday', id: 'yesterday' },
              { label: 'Last 7 Days', id: '7d' },
              { label: 'Last 30 Days (Month)', id: '30d' },
              { label: 'Month to Date', id: 'mtd' },
              { label: 'Last 365 Days', id: '365d' },
              { label: 'Custom Range...', id: 'custom' },
            ].map((p) => (
              <button
                key={p.id}
                type="button"
                className={`archive-preset-chip ${archivePreset === p.id ? 'active' : ''}`}
                onClick={() => applyArchivePreset(p.id)}
              >
                {p.label}
              </button>
            ))}
          </section>

          {/* Archive Totals Summary Cards */}
          <section className="archive-totals-strip">
            <div className="archive-total-card">
              <span className="archive-total-label">Total Passes in Range</span>
              <span className="archive-total-num">{archiveTotals.total}</span>
              <span className="archive-total-note">Gate crossings recorded</span>
            </div>
            <div className="archive-total-card">
              <span className="archive-total-label">Commercial Freight</span>
              <span className="archive-total-num">{archiveTotals.trucks}</span>
              <span className="archive-total-note">Heavy transport trucks</span>
            </div>
            <div className="archive-total-card">
              <span className="archive-total-label">Regulated Cargo</span>
              <span className="archive-total-num">{archiveTotals.regulatedCargo}</span>
              <span className="archive-total-note">Timber, bamboo, minerals</span>
            </div>
            <div className="archive-total-card">
              <span className="archive-total-label">Flagged for Inspection</span>
              <span className="archive-total-num" style={{ color: archiveTotals.needsReview > 0 ? '#D97706' : '#0F172A' }}>
                {archiveTotals.needsReview}
              </span>
              <span className="archive-total-note">Physical check required</span>
            </div>
            <div className="archive-total-card">
              <span className="archive-total-label">Stopped at Gate</span>
              <span className="archive-total-num" style={{ color: 'var(--forest-green-700)' }}>
                {archiveTotals.stoppedPasses}
              </span>
              <span className="archive-total-note">0.0 km/h [STOPPED] compliant</span>
            </div>
          </section>

          {/* Archive Filter & Search Toolbar */}
          <section className="gov-toolbar" style={{ margin: '0' }}>
            <div className="gov-search-input-box">
              <Search size={15} className="gov-search-icon" />
              <input
                type="text"
                className="gov-search-input"
                placeholder="Search historical vehicle plate..."
                value={archiveSearchPlate}
                onChange={(e) => {
                  setArchiveSearchPlate(e.target.value);
                  setArchivePage(1);
                }}
              />
              {archiveSearchPlate && (
                <button
                  className="btn-gov-icon"
                  style={{ position: 'absolute', right: '0.4rem', padding: '0.2rem', background: 'transparent', border: 'none' }}
                  onClick={() => setArchiveSearchPlate('')}
                >
                  <X size={14} color="var(--text-muted)" />
                </button>
              )}
            </div>

            <div className="gov-toolbar-filters">
              <select
                className="gov-select-control"
                value={archiveVehicleType}
                onChange={(e) => {
                  setArchiveVehicleType(e.target.value);
                  setArchivePage(1);
                }}
              >
                <option value="">All Vehicle Classes</option>
                <option value="motorcycle">Two-Wheeler</option>
                <option value="truck">Heavy Truck</option>
                <option value="car">Car / SUV</option>
                <option value="pickup">Pickup</option>
                <option value="van">Van</option>
                <option value="bus">Bus</option>
              </select>

              <select
                className="gov-select-control"
                value={archiveLoadType}
                onChange={(e) => {
                  setArchiveLoadType(e.target.value);
                  setArchivePage(1);
                }}
              >
                <option value="">All Cargo Categories</option>
                <option value="timber_logs">Timber Logs</option>
                <option value="bamboo">Bamboo</option>
                <option value="sand">Sand / Mineral</option>
                <option value="stone_gravel">Stone / Gravel</option>
                <option value="bags">Agricultural Bags</option>
                <option value="empty">Empty Bed</option>
              </select>

              <select
                className="gov-select-control"
                value={archiveStatus}
                onChange={(e) => {
                  setArchiveStatus(e.target.value);
                  setArchivePage(1);
                }}
              >
                <option value="">All Clearance Statuses</option>
                <option value="verified">Verified</option>
                <option value="needs_review">Inspection Required</option>
                <option value="corrected">Corrected</option>
              </select>

              <button className="btn-gov" onClick={handleExportArchiveCSV} title="Export current archive date range to CSV">
                <Download size={13} /> Export Archive CSV
              </button>
            </div>
          </section>

          {/* Historical Passes Table */}
          <main className="gov-register-container" style={{ margin: '0' }}>
            {archiveFilteredDetections.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '3.5rem 1.5rem', background: '#FFFFFF' }}>
                <History size={36} color="var(--text-muted)" style={{ margin: '0 auto 0.75rem' }} />
                <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#0F172A' }}>
                  No Historical Records Found in Selected Range
                </h3>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.25rem' }}>
                  Try selecting a broader date range like "Last 30 Days" or "Last 365 Days".
                </p>
                <div style={{ marginTop: '1rem' }}>
                  <button className="btn-gov" onClick={() => applyArchivePreset('30d')}>
                    <Calendar size={13} /> Switch to Last 30 Days
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="gov-register-table-wrapper">
                  <table className="gov-register-table">
                    <thead>
                      <tr>
                        <th>Pass #</th>
                        <th>Registration (Plate Photo & HSRP)</th>
                        <th>Vehicle Class & Speed</th>
                        <th>Declared Cargo</th>
                        <th>Transit Date & Time</th>
                        <th>Clearance</th>
                        <th>Evidence (Front / Back)</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paginatedArchive.map((d, idx) => (
                        <tr key={d.id || idx}>
                          <td>
                            <span className="serial-stamp">#{String(d.day_serial || idx + 1).padStart(3, '0')}</span>
                          </td>
                          <td>
                            <div className="plate-identity-cell">
                              {getPhotoUrl(d, 'plate') ? (
                                <div
                                  className="plate-crop-thumb-box"
                                  onClick={() => {
                                    const u = getPhotoUrl(d, 'plate');
                                    if (u) setZoomedPhoto({ url: u, title: `Plate Photo — Pass #${d.day_serial || d.id}` });
                                  }}
                                  title="Actual camera plate photo — Click to zoom"
                                >
                                  <img
                                    src={getPhotoUrl(d, 'plate')}
                                    alt="Plate Crop"
                                    className="plate-crop-thumb-img"
                                  />
                                </div>
                              ) : (
                                <div className="plate-crop-placeholder">
                                  <Camera size={13} />
                                </div>
                              )}
                              <div className="plate-text-stack">
                                <HsrpPlate plate={d.plate} rawPlate={d.plate_raw} isValid={d.plate_valid} />
                                <span className="plate-conf-stat">
                                  {Math.round((d.plate_conf || 1) * 100)}% Conf
                                </span>
                              </div>
                            </div>
                          </td>
                          <td>
                            <div style={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                              {d.vehicle_type === 'motorcycle' && <Bike size={14} color="var(--forest-green-700)" />}
                              {d.vehicle_type === 'truck' && <Truck size={14} color="var(--gov-navy-400)" />}
                              {d.vehicle_type === 'car' && <Car size={14} color="var(--text-muted)" />}
                              <span>{d.vehicle_make ? `${d.vehicle_make} ${d.vehicle_model || ''}` : d.vehicle_type}</span>
                            </div>
                            <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)', textTransform: 'capitalize' }}>
                              Color: {d.vehicle_color || 'Unknown'} •{' '}
                              {d.speed_kph === 0 ? (
                                <span className="speed-pill stopped">🛑 0.0 km/h (Stopped)</span>
                              ) : (
                                <span className="speed-pill moving">⚡ {d.speed_kph} km/h</span>
                              )}
                            </div>
                          </td>
                          <td>
                            <span style={{ textTransform: 'capitalize', fontWeight: 600 }}>
                              {['motorcycle', 'car'].includes(d.vehicle_type) ? 'Passenger (N/A)' : d.load_type ? d.load_type.replace(/_/g, ' ') : 'N/A'}
                            </span>
                          </td>
                          <td style={{ whiteSpace: 'nowrap' }}>
                            <div style={{ fontWeight: 600 }}>{formatTransitTime(d.captured_at)}</div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                              {parseUtcDate(d.captured_at).toLocaleDateString('en-IN', {
                                day: 'numeric',
                                month: 'short',
                                year: 'numeric',
                              })}
                            </div>
                          </td>
                          <td>
                            <span className={`clearance-badge ${d.status === 'verified' ? 'verified' : d.status === 'needs_review' ? 'inspection' : 'corrected'}`}>
                              {d.status === 'verified' && <CheckCircle2 size={12} />}
                              {d.status === 'needs_review' && <AlertTriangle size={12} />}
                              {d.status.replace(/_/g, ' ')}
                            </span>
                          </td>
                          <td>
                            <div className="evidence-dual-thumbs">
                              {getPhotoUrl(d, 'scene') && (
                                <div
                                  className="evidence-thumb-card"
                                  onClick={() => setActiveDossier(d)}
                                  title="Front Photo"
                                >
                                  <div className="evidence-thumb-img-wrapper">
                                    <img src={getPhotoUrl(d, 'scene')} alt="Front" />
                                  </div>
                                  <span className="evidence-thumb-tag">Front</span>
                                </div>
                              )}
                              {(getPhotoUrl(d, 'load_thumb') || getPhotoUrl(d, 'scene')) && (
                                <div
                                  className="evidence-thumb-card"
                                  onClick={() => setActiveDossier(d)}
                                  title="Back Photo"
                                >
                                  <div className="evidence-thumb-img-wrapper">
                                    <img src={getPhotoUrl(d, 'load_thumb') || getPhotoUrl(d, 'scene')} alt="Back" />
                                  </div>
                                  <span className="evidence-thumb-tag">Back</span>
                                </div>
                              )}
                            </div>
                          </td>
                          <td>
                            <button
                              type="button"
                              className="btn-gov"
                              onClick={() => setActiveDossier(d)}
                              title="Inspect 3-Photo Evidentiary Dossier"
                              style={{ color: 'var(--forest-green-700)', borderColor: 'var(--forest-green-border)' }}
                            >
                              <FileText size={12} /> Dossier
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Pagination Controls using user-requested Pagination5 */}
                <div style={{ padding: '1rem', borderTop: '1px solid var(--gov-border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem', background: '#FFFFFF' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                    Showing records <strong>{(archivePage - 1) * archivePageSize + 1}</strong> to{' '}
                    <strong>{Math.min(archivePage * archivePageSize, archiveFilteredDetections.length)}</strong> of{' '}
                    <strong>{archiveFilteredDetections.length}</strong> total passes
                  </div>
                  <Pagination5
                    currentPage={archivePage}
                    totalPages={totalArchivePages}
                    onPageChange={(p) => setArchivePage(p)}
                  />
                </div>
              </>
            )}
          </main>
        </div>
      )}

      {/* ====================================================================
          MODAL: SCHEDULE DATE PICKER (User Requested Component)
          ==================================================================== */}
      {showScheduleModal && (
        <div className="gov-modal-backdrop" onClick={() => setShowScheduleModal(false)}>
          <div onClick={(e) => e.stopPropagation()}>
            <ScheduleDate
              initialRange={archiveRange}
              onApply={(range) => {
                setArchiveRange(range);
                setArchivePage(1);
                setShowScheduleModal(false);
                showToast('Audit date range updated successfully');
              }}
              onCancel={() => setShowScheduleModal(false)}
            />
          </div>
        </div>
      )}

      {/* ====================================================================
          MODAL: 3-PHOTO TRANSIT EVIDENCE DOSSIER
          ==================================================================== */}
      {activeDossier && (
        <div className="gov-modal-backdrop" onClick={() => setActiveDossier(null)}>
          <div className="gov-modal-box dossier-modal" onClick={(e) => e.stopPropagation()}>
            <div className="gov-modal-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                <div className="serial-stamp" style={{ fontSize: '0.85rem', padding: '0.3rem 0.6rem' }}>
                  PASS #{String(activeDossier.day_serial || activeDossier.id).padStart(3, '0')}
                </div>
                <HsrpPlate
                  plate={activeDossier.plate}
                  rawPlate={activeDossier.plate_raw}
                  isValid={activeDossier.plate_valid}
                />
                <span className={`clearance-badge ${activeDossier.status === 'verified' ? 'verified' : activeDossier.status === 'needs_review' ? 'inspection' : 'corrected'}`}>
                  {activeDossier.status.replace(/_/g, ' ')}
                </span>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <button
                  className="btn-gov"
                  onClick={() => downloadEvidencePhotos(activeDossier)}
                  title="Download all 3 high-resolution evidence photos"
                >
                  <Download size={13} /> Download 3 Photos
                </button>
                <button
                  className="btn-gov-icon"
                  onClick={() => setActiveDossier(null)}
                  title="Close Dossier"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            <div className="gov-modal-body" style={{ maxHeight: 'calc(90vh - 120px)' }}>
              {/* 3-Photo Evidentiary Grid */}
              <div className="dossier-photos-grid">
                {/* Photo 1: License Plate Crop */}
                <div className="dossier-photo-card">
                  <div className="dossier-photo-card-header">
                    <span>1. HSRP Plate Crop</span>
                    <span style={{ color: 'var(--forest-green-700)' }}>
                      {Math.round((activeDossier.plate_conf || 1) * 100)}% Conf
                    </span>
                  </div>
                  <div
                    className="dossier-photo-viewport"
                    onClick={() => {
                      const u = getPhotoUrl(activeDossier, 'plate');
                      if (u) setZoomedPhoto({ url: u, title: `Plate Crop — Pass #${activeDossier.day_serial}` });
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    {getPhotoUrl(activeDossier, 'plate') ? (
                      <img
                        src={getPhotoUrl(activeDossier, 'plate')}
                        alt="Plate Close-Up"
                        className="dossier-photo-img"
                      />
                    ) : (
                      <div style={{ color: '#94A3B8', fontSize: '0.8rem' }}>No Plate Photo Available</div>
                    )}
                  </div>
                  <div style={{ padding: '0.65rem', background: '#FFFFFF', fontSize: '0.75rem' }}>
                    <strong>Extracted:</strong> {activeDossier.plate || activeDossier.plate_raw}
                  </div>
                </div>

                {/* Photo 2: Front Vehicle Scene Overview */}
                <div className="dossier-photo-card">
                  <div className="dossier-photo-card-header">
                    <span>2. Front Vehicle Overview (Gate)</span>
                    <span style={{ textTransform: 'capitalize' }}>{activeDossier.vehicle_type}</span>
                  </div>
                  <div
                    className="dossier-photo-viewport"
                    onClick={() => {
                      const u = getPhotoUrl(activeDossier, 'scene');
                      if (u) setZoomedPhoto({ url: u, title: `Front Vehicle Overview — Pass #${activeDossier.day_serial}` });
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    {getPhotoUrl(activeDossier, 'scene') ? (
                      <img
                        src={getPhotoUrl(activeDossier, 'scene')}
                        alt="Vehicle Front"
                        className="dossier-photo-img"
                      />
                    ) : (
                      <div style={{ color: '#94A3B8', fontSize: '0.8rem' }}>No Vehicle Photo Available</div>
                    )}
                  </div>
                  <div style={{ padding: '0.65rem', background: '#FFFFFF', fontSize: '0.75rem' }}>
                    <strong>Color:</strong> {activeDossier.vehicle_color || 'Unknown'}
                  </div>
                </div>

                {/* Photo 3: Back of Car / Cargo Bed Overview */}
                <div className="dossier-photo-card">
                  <div className="dossier-photo-card-header">
                    <span>3. Rear View / Back of Car</span>
                    <span>{activeDossier.load_type ? activeDossier.load_type.replace(/_/g, ' ') : 'N/A'}</span>
                  </div>
                  <div
                    className="dossier-photo-viewport"
                    onClick={() => {
                      const u = getPhotoUrl(activeDossier, 'load_thumb') || getPhotoUrl(activeDossier, 'scene');
                      if (u) setZoomedPhoto({ url: u, title: `Rear Vehicle / Back View — Pass #${activeDossier.day_serial}` });
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    {getPhotoUrl(activeDossier, 'load_thumb') || getPhotoUrl(activeDossier, 'scene') ? (
                      <img
                        src={getPhotoUrl(activeDossier, 'load_thumb') || getPhotoUrl(activeDossier, 'scene')}
                        alt="Rear Vehicle / Back View"
                        className="dossier-photo-img"
                      />
                    ) : (
                      <div style={{ color: '#94A3B8', fontSize: '0.8rem' }}>Rear view not captured</div>
                    )}
                  </div>
                  <div style={{ padding: '0.65rem', background: '#FFFFFF', fontSize: '0.75rem' }}>
                    <strong>Cargo / Classification:</strong> {['motorcycle', 'car'].includes(activeDossier.vehicle_type) ? 'Passenger (No Cargo)' : activeDossier.load_type ? activeDossier.load_type.replace(/_/g, ' ') : 'N/A'}
                  </div>
                </div>
              </div>

              {/* Dossier Gate Metadata Table */}
              <div style={{ background: '#F8FAFC', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--gov-border-subtle)' }}>
                <table className="dossier-meta-table">
                  <tbody>
                    <tr>
                      <td>Checkpost Location:</td>
                      <td>Checkpost 01 — Pine Valley Reserve Forest, Chhattisgarh</td>
                    </tr>
                    <tr>
                      <td>GPS Coordinates:</td>
                      <td>
                        21.1938° N, 81.2849° E{' '}
                        <a
                          href="https://maps.google.com/?q=21.1938,81.2849"
                          target="_blank"
                          rel="noreferrer"
                          style={{ color: '#0284C7', marginLeft: '0.5rem', textDecoration: 'underline' }}
                        >
                          View on Map <ExternalLink size={11} style={{ display: 'inline' }} />
                        </a>
                      </td>
                    </tr>
                    <tr>
                      <td>Transit Time (IST):</td>
                      <td>{formatTransitTime(activeDossier.captured_at)} ({formatTimeAgo(activeDossier.captured_at)})</td>
                    </tr>
                    <tr>
                      <td>Speed & Motion:</td>
                      <td>
                        {activeDossier.speed_kph === 0 ? (
                          <strong style={{ color: '#D97706' }}>0.0 km/h [STOPPED AT GATE] (Verified Stationary)</strong>
                        ) : (
                          `${activeDossier.speed_kph} km/h (${activeDossier.direction || 'Egress'})`
                        )}
                      </td>
                    </tr>
                    <tr>
                      <td>Clearance Status:</td>
                      <td>
                        <strong style={{ textTransform: 'capitalize' }}>{activeDossier.status.replace(/_/g, ' ')}</strong>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div className="gov-modal-footer">
              {activeDossier.status !== 'verified' && (
                <button
                  type="button"
                  className="btn-gov primary"
                  onClick={() => handleQuickVerify(activeDossier.id)}
                >
                  <CheckCircle2 size={13} /> Verify & Clear Pass
                </button>
              )}
              <button
                type="button"
                className="btn-gov"
                onClick={() => setActiveDossier(null)}
              >
                Close Dossier
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ====================================================================
          MODAL: FULL PHOTO ZOOM
          ==================================================================== */}
      {zoomedPhoto && (
        <div className="gov-modal-backdrop" onClick={() => setZoomedPhoto(null)}>
          <div
            className="gov-modal-box"
            style={{ maxWidth: '900px', width: '95%' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="gov-modal-header">
              <h3 style={{ fontSize: '0.95rem', fontWeight: 700, color: '#0F172A' }}>
                {zoomedPhoto.title}
              </h3>
              <button className="btn-gov-icon" onClick={() => setZoomedPhoto(null)}>
                <X size={16} />
              </button>
            </div>
            <div className="gov-modal-body" style={{ padding: '0', background: '#0F172A', display: 'flex', justifyContent: 'center' }}>
              <img
                src={zoomedPhoto.url}
                alt={zoomedPhoto.title}
                style={{ maxWidth: '100%', maxHeight: '78vh', objectFit: 'contain' }}
              />
            </div>
            <div className="gov-modal-footer">
              <a href={zoomedPhoto.url} download className="btn-gov">
                <Download size={13} /> Save Photo
              </a>
              <button className="btn-gov primary" onClick={() => setZoomedPhoto(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ====================================================================
          MODAL: 24/7 CCTV CONTINUOUS RECORDINGS
          ==================================================================== */}
      {showRecordingsModal && (
        <div className="gov-modal-backdrop" onClick={() => setShowRecordingsModal(false)}>
          <div
            className="gov-modal-box"
            style={{ maxWidth: '800px', width: '92%' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="gov-modal-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                <Video size={18} color="#DC2626" />
                <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#0F172A' }}>
                  24/7 Continuous CCTV Video Archive
                </h3>
              </div>
              <button className="btn-gov-icon" onClick={() => setShowRecordingsModal(false)}>
                <X size={16} />
              </button>
            </div>

            <div className="gov-modal-body" style={{ maxHeight: '75vh', overflowY: 'auto' }}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  background: '#F8FAFC',
                  padding: '0.75rem 1rem',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--gov-border-subtle)',
                }}
              >
                <div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                    Storage Repository
                  </div>
                  <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--forest-green-700)', fontFamily: 'var(--font-mono)' }}>
                    ./recordings/ (Local HDD / Edge SSD)
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Archived Space</div>
                  <div style={{ fontSize: '0.9rem', fontWeight: 800, color: '#0F172A' }}>
                    {recordingsTotalMb} MB ({recordingsList.length} files)
                  </div>
                </div>
              </div>

              {activeVideoUrl && (
                <div style={{ marginTop: '1rem', background: '#000', borderRadius: '8px', overflow: 'hidden' }}>
                  <div style={{ padding: '0.5rem 0.75rem', background: '#0F172A', color: '#FFF', fontSize: '0.75rem', display: 'flex', justifyContent: 'space-between' }}>
                    <span>Continuous Video Playback</span>
                    <button style={{ background: 'none', border: 'none', color: '#94A3B8', cursor: 'pointer' }} onClick={() => setActiveVideoUrl(null)}>
                      Close Player
                    </button>
                  </div>
                  <video src={activeVideoUrl} controls autoPlay style={{ width: '100%', maxHeight: '360px', display: 'block' }} />
                </div>
              )}

              <div style={{ marginTop: '1rem' }}>
                {recordingsLoading ? (
                  <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                    <RefreshCw size={20} /> Loading video segments...
                  </div>
                ) : recordingsList.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                    No continuous recording files found in ./recordings yet.
                  </div>
                ) : (
                  <div className="cctv-recordings-grid">
                    {recordingsList.map((rec, idx) => (
                      <div
                        key={idx}
                        className={`cctv-recordings-card ${activeVideoUrl && activeVideoUrl.includes(rec.filename) ? 'active' : ''}`}
                        onClick={() => setActiveVideoUrl(`${API_BASE}${rec.stream_url}`)}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          <Video size={14} color="#DC2626" />
                          <span style={{ fontSize: '0.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: '#0F172A' }}>
                            {rec.filename}
                          </span>
                        </div>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                          {rec.date} • {rec.camera} • {rec.size_mb} MB
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="gov-modal-footer">
              <button className="btn-gov" onClick={fetchRecordings}>
                <RefreshCw size={13} /> Refresh List
              </button>
              <button className="btn-gov primary" onClick={() => setShowRecordingsModal(false)}>
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ====================================================================
          MODAL: OFFICER LOGIN
          ==================================================================== */}
      {/* ====================================================================
          MODAL: OFFICE STAFF ACCOUNT MANAGEMENT (ADMIN ONLY)
          ==================================================================== */}
      {showUsersModal && (
        <div className="gov-modal-backdrop" onClick={() => setShowUsersModal(false)}>
          <div className="gov-modal-box" style={{ maxWidth: '580px' }} onClick={(e) => e.stopPropagation()}>
            <div className="gov-modal-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Users size={18} color="var(--forest-green-700)" />
                <h3 style={{ fontSize: '0.95rem', fontWeight: 700, color: '#0F172A' }}>
                  Office Staff Logins &amp; Access Control
                </h3>
              </div>
              <button className="btn-gov-icon" onClick={() => setShowUsersModal(false)}>
                <X size={16} />
              </button>
            </div>
            <div className="gov-modal-body" style={{ maxHeight: '65vh', overflowY: 'auto' }}>
              <div style={{ marginBottom: '1rem' }}>
                <h4 style={{ fontSize: '0.8rem', fontWeight: 700, color: '#0F172A', marginBottom: '0.25rem' }}>
                  Authorized Checkpost Accounts
                </h4>
                <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                  Only authorized personnel listed below can log into the ANPR portal.
                </p>
                <table className="gov-users-table">
                  <thead>
                    <tr>
                      <th>Username</th>
                      <th>Role</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usersList.length === 0 ? (
                      <tr>
                        <td colSpan={3} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                          Loading personnel list...
                        </td>
                      </tr>
                    ) : (
                      usersList.map((u) => (
                        <tr key={u.id}>
                          <td style={{ fontWeight: 600 }}>{u.username}</td>
                          <td>
                            <span className={`gov-role-pill ${u.role}`}>{u.role}</span>
                          </td>
                          <td>
                            <span style={{ color: u.active ? '#16A34A' : '#DC2626', fontWeight: 600, fontSize: '0.72rem' }}>
                              {u.active ? '● Active' : '○ Inactive'}
                            </span>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              <div style={{ borderTop: '1px solid var(--gov-border-subtle)', paddingTop: '1rem' }}>
                <h4 style={{ fontSize: '0.8rem', fontWeight: 700, color: '#0F172A', marginBottom: '0.5rem' }}>
                  Create New Officer Account
                </h4>
                {userFormError && (
                  <div style={{ padding: '0.5rem 0.75rem', background: '#FEE2E2', color: '#DC2626', borderRadius: 'var(--radius-xs)', fontSize: '0.75rem', marginBottom: '0.65rem' }}>
                    {userFormError}
                  </div>
                )}
                <form onSubmit={handleCreateUser} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: '0.5rem', alignItems: 'end' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                      Username
                    </label>
                    <input
                      type="text"
                      className="gov-search-input"
                      placeholder="e.g. officer_kumar"
                      value={newUserForm.username}
                      onChange={(e) => setNewUserForm({ ...newUserForm, username: e.target.value })}
                      required
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                      Password
                    </label>
                    <input
                      type="password"
                      className="gov-search-input"
                      placeholder="Min 8 characters"
                      value={newUserForm.password}
                      onChange={(e) => setNewUserForm({ ...newUserForm, password: e.target.value })}
                      required
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                      Role
                    </label>
                    <select
                      className="gov-search-input"
                      value={newUserForm.role}
                      onChange={(e) => setNewUserForm({ ...newUserForm, role: e.target.value })}
                    >
                      <option value="reviewer">Reviewer (Officer)</option>
                      <option value="viewer">Viewer (Monitor)</option>
                      <option value="admin">Admin (Manager)</option>
                    </select>
                  </div>
                  <div style={{ gridColumn: 'span 3', display: 'flex', justifyContent: 'flex-end', marginTop: '0.25rem' }}>
                    <button type="submit" className="btn-gov primary" style={{ fontSize: '0.78rem' }}>
                      <UserPlus size={13} /> Add Officer Account
                    </button>
                  </div>
                </form>
              </div>
            </div>
            <div className="gov-modal-footer">
              <button type="button" className="btn-gov" onClick={() => setShowUsersModal(false)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ====================================================================
          MODAL: MANUAL RECORD CORRECTION
          ==================================================================== */}
      {editingDetection && (
        <div className="gov-modal-backdrop" onClick={() => setEditingDetection(null)}>
          <div className="gov-modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="gov-modal-header">
              <h3 style={{ fontSize: '0.95rem', fontWeight: 700, color: '#0F172A' }}>
                Manual Inspection & Review — Pass #{String(editingDetection.day_serial || editingDetection.id).padStart(3, '0')}
              </h3>
              <button className="btn-gov-icon" onClick={() => setEditingDetection(null)}>
                <X size={16} />
              </button>
            </div>
            <form onSubmit={handleCorrectionSubmit}>
              <div className="gov-modal-body">
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                    License Plate (HSRP)
                  </label>
                  <input
                    type="text"
                    className="gov-search-input"
                    value={correctionForm.plate}
                    onChange={(e) => setCorrectionForm({ ...correctionForm, plate: e.target.value.toUpperCase() })}
                    required
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                    Vehicle Class
                  </label>
                  <select
                    className="gov-select-control"
                    style={{ width: '100%' }}
                    value={correctionForm.vehicle_type}
                    onChange={(e) => setCorrectionForm({ ...correctionForm, vehicle_type: e.target.value })}
                  >
                    <option value="motorcycle">Two-Wheeler (Motorcycle / Scooter)</option>
                    <option value="truck">Heavy Truck</option>
                    <option value="car">Car / SUV</option>
                    <option value="pickup">Pickup</option>
                    <option value="van">Van</option>
                    <option value="bus">Bus</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                    Cargo Type
                  </label>
                  <select
                    className="gov-select-control"
                    style={{ width: '100%' }}
                    value={correctionForm.load_type}
                    onChange={(e) => setCorrectionForm({ ...correctionForm, load_type: e.target.value })}
                  >
                    <option value="timber_logs">Timber Logs</option>
                    <option value="bamboo">Bamboo</option>
                    <option value="sand">Sand / Mineral</option>
                    <option value="stone_gravel">Stone / Gravel</option>
                    <option value="bags">Agricultural Bags</option>
                    <option value="empty">Empty Bed</option>
                  </select>
                </div>
              </div>
              <div className="gov-modal-footer">
                <button type="button" className="btn-gov" onClick={() => setEditingDetection(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn-gov primary">
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { ChevronLeft, ChevronRight, Check, ChevronDown, Calendar as CalendarIcon } from 'lucide-react';
import { cn } from '@/lib/utils';

export const PRESETS = [
  { label: 'Today', id: 'today' },
  { label: 'Yesterday', id: 'yesterday' },
  { label: 'Last 7 Days', id: '7d' },
  { label: 'Last 30 Days', id: '30d' },
  { label: 'Last 365 Days', id: '365d' },
  { label: 'Week to Date', id: 'wtd' },
  { label: 'Month to Date', id: 'mtd' },
  { label: 'Year to Date', id: 'ytd' },
  { label: 'Custom Range', id: 'custom' },
];

const DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];

export const ScheduleDate = ({
  onApply,
  onCancel,
  initialRange,
}) => {
  const now = new Date();
  const [selectedPreset, setSelectedPreset] = useState('7d');
  const [viewDate, setViewDate] = useState(new Date(now.getFullYear(), now.getMonth(), 1));
  const [range, setRange] = useState(
    initialRange || {
      start: new Date(now.getTime() - 7 * 86400000),
      end: now,
    }
  );

  const applyPreset = (presetId) => {
    setSelectedPreset(presetId);
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
      const dayOfWeek = (today.getDay() + 6) % 7; // Monday = 0
      newStart = new Date(startOfToday.getTime() - dayOfWeek * 86400000);
    } else if (presetId === 'mtd') {
      newStart = new Date(today.getFullYear(), today.getMonth(), 1);
    } else if (presetId === 'ytd') {
      newStart = new Date(today.getFullYear(), 0, 1);
    } else {
      return;
    }

    setRange({ start: newStart, end: newEnd });
    setViewDate(new Date(newStart.getFullYear(), newStart.getMonth(), 1));
  };

  const handleDateClick = (date) => {
    if (!range.start || (range.start && range.end)) {
      setRange({ start: date, end: null });
      setSelectedPreset('custom');
    } else {
      if (date < range.start) {
        setRange({ start: date, end: range.start });
      } else {
        setRange({ ...range, end: date });
      }
    }
  };

  const renderMonthGrid = (
    monthDate,
    showLeftNav = false,
    showRightNav = false,
  ) => {
    const year = monthDate.getFullYear();
    const month = monthDate.getMonth();
    const firstDay = (new Date(year, month, 1).getDay() + 6) % 7;
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const monthName = monthDate.toLocaleString('default', {
      month: 'long',
      year: 'numeric',
    });

    return (
      <div className="schedule-month-col">
        <div className="schedule-month-header">
          {showLeftNav ? (
            <button
              type="button"
              title="Previous Month"
              onClick={() => setViewDate(new Date(year, month - 1, 1))}
              className="schedule-nav-btn"
            >
              <ChevronLeft size={16} strokeWidth={2.5} />
            </button>
          ) : (
            <div className="schedule-nav-placeholder" />
          )}
          <span className="schedule-month-title">
            {monthName}
          </span>
          {showRightNav ? (
            <button
              type="button"
              title="Next Month"
              onClick={() => setViewDate(new Date(year, month + 1, 1))}
              className="schedule-nav-btn"
            >
              <ChevronRight size={16} strokeWidth={2.5} />
            </button>
          ) : (
            <div className="schedule-nav-placeholder" />
          )}
        </div>

        <div className="schedule-days-grid">
          {DAYS.map((d) => (
            <span key={d} className="schedule-day-label">
              {d}
            </span>
          ))}
          {Array.from({ length: firstDay }).map((_, i) => (
            <div key={`empty-${i}`} className="schedule-day-empty" />
          ))}
          {Array.from({ length: daysInMonth }).map((_, i) => {
            const day = i + 1;
            const currentDayDate = new Date(year, month, day);
            const isStart =
              range.start && range.start.toDateString() === currentDayDate.toDateString();
            const isEnd =
              range.end && range.end.toDateString() === currentDayDate.toDateString();
            const isInRange =
              range.start &&
              range.end &&
              currentDayDate > range.start &&
              currentDayDate < range.end;

            return (
              <div
                key={day}
                onClick={() => handleDateClick(currentDayDate)}
                className="schedule-day-cell group"
              >
                {(isInRange || isStart || isEnd) && (
                  <div
                    className={cn(
                      'schedule-range-highlight',
                      isStart && 'is-start',
                      isEnd && 'is-end',
                      isInRange && !isStart && !isEnd && 'is-in-range'
                    )}
                  />
                )}
                {isStart || isEnd ? (
                  <div className="schedule-day-selected">
                    <span className="schedule-day-num active">{day}</span>
                    <motion.div
                      layoutId="activeThumb"
                      className="schedule-day-dot"
                    />
                  </div>
                ) : (
                  <span
                    className={cn(
                      'schedule-day-num',
                      isInRange ? 'in-range' : 'normal'
                    )}
                  >
                    {day}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <div className="schedule-date-modal-card">
      <div className="schedule-date-body">
        {/* Preset Sidebar */}
        <aside className="schedule-sidebar">
          <div className="schedule-sidebar-title">
            <CalendarIcon size={14} className="text-forest-600" /> Date Presets
          </div>
          {PRESETS.map((preset, idx) => (
            <React.Fragment key={preset.id}>
              {[2, 5, 8].includes(idx) && (
                <div className="schedule-sidebar-divider" />
              )}
              <button
                type="button"
                onClick={() => applyPreset(preset.id)}
                className={cn(
                  'schedule-preset-btn',
                  selectedPreset === preset.id && 'is-active'
                )}
              >
                <span>{preset.label}</span>
                {selectedPreset === preset.id && (
                  <motion.div
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    className="preset-check"
                  >
                    <Check size={12} strokeWidth={3} />
                  </motion.div>
                )}
              </button>
            </React.Fragment>
          ))}
        </aside>

        {/* Main Content Area */}
        <main className="schedule-main-content">
          {/* Inputs Row */}
          <div className="schedule-inputs-row">
            <DateInput label="Audit Start Date" date={range.start} />
            <DateInput label="Audit End Date" date={range.end} />
          </div>

          {/* Calendars Container (2 Months) */}
          <div className="schedule-calendars-row">
            <div className="schedule-calendar-pane">
              {renderMonthGrid(viewDate, true, false)}
            </div>

            <div className="schedule-month-divider" />

            <div className="schedule-calendar-pane">
              {renderMonthGrid(
                new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 1),
                false,
                true
              )}
            </div>
          </div>
        </main>
      </div>

      {/* Modal Action Footer */}
      <footer className="schedule-footer">
        <div className="schedule-footer-hint">
          {range.start && range.end ? (
            <span>
              Showing transit logs from <strong>{range.start.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}</strong> to <strong>{range.end.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}</strong>
            </span>
          ) : (
            <span>Select start and end dates from calendar</span>
          )}
        </div>
        <div className="schedule-footer-btns">
          <button
            type="button"
            onClick={onCancel}
            className="schedule-btn-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onApply?.(range)}
            className="schedule-btn-apply"
          >
            Apply Date Range
          </button>
        </div>
      </footer>
    </div>
  );
};

const DateInput = ({ label, date }) => (
  <div className="schedule-input-group">
    <label className="schedule-input-label">{label}</label>
    <div className="schedule-input-box">
      <span>
        {date
          ? date.toLocaleDateString('en-IN', {
              day: 'numeric',
              month: 'short',
              year: 'numeric',
            })
          : 'Select Date'}
      </span>
      <ChevronDown size={14} className="text-slate-400" />
    </div>
  </div>
);

export default ScheduleDate;

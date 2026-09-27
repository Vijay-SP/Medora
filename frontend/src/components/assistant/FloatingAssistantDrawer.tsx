import React, { useState, useRef, useEffect } from 'react';
import {
  Sparkles,
  X,
  Minus,
  Send,
  Loader2,
  Bot,
  User,
  Calendar,
  AlertCircle,
  TrendingDown,
  Users,
  CheckCircle2,
  RotateCcw,
  ExternalLink,
} from 'lucide-react';
import { apiClient } from '../../api/client';
import { AssistantChatMessage, ReferencedMeeting } from '../../types';

interface FloatingAssistantDrawerProps {
  currentMeetingId?: string;
  onNavigateToMeeting?: (meetingId: string) => void;
}

interface MessageItem {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  referencedMeetings?: ReferencedMeeting[];
  isError?: boolean;
}

const QUICK_PROMPTS = [
  {
    icon: TrendingDown,
    label: 'Where are we lagging?',
    query: 'Where are we lagging across our meetings? Which tasks are pending or have no deadlines?',
  },
  {
    icon: Calendar,
    label: 'Decisions last week',
    query: 'How many decisions did we make last week and in which categories?',
  },
  {
    icon: Users,
    label: 'Task load by person',
    query: 'Which employee or doctor has the most assigned tasks and decisions?',
  },
  {
    icon: CheckCircle2,
    label: 'Meeting outcomes overview',
    query: 'Can you give me an executive overview of the outcomes from our recent meetings?',
  },
];

export const FloatingAssistantDrawer: React.FC<FloatingAssistantDrawerProps> = ({
  currentMeetingId,
  onNavigateToMeeting,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [inputQuery, setInputQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState<MessageItem[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        'Hello! I am your **Medora Executive Intelligence Assistant**. I have complete, air-gapped visibility across all hospital council meetings, adopted decisions, action plans, and attendee workloads.\n\nHow can I help you today? You can ask about lagging tasks, decision metrics, or meeting overviews.',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    },
  ]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen && !isMinimized) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isOpen, isMinimized]);

  useEffect(() => {
    if (isOpen && !isMinimized) {
      inputRef.current?.focus();
    }
  }, [isOpen, isMinimized]);

  const handleSendMessage = async (textToSend?: string) => {
    const query = (textToSend || inputQuery).trim();
    if (!query || isLoading) return;

    const userMsgId = `user-${Date.now()}`;
    const userMessage: MessageItem = {
      id: userMsgId,
      role: 'user',
      content: query,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputQuery('');
    setIsLoading(true);

    try {
      const historyPayload: AssistantChatMessage[] = messages
        .filter((m) => !m.isError && m.id !== 'welcome')
        .map((m) => ({
          role: m.role,
          content: m.content,
        }));

      const response = await apiClient.queryAssistant(query, historyPayload, currentMeetingId);

      const assistantMsg: MessageItem = {
        id: `asst-${Date.now()}`,
        role: 'assistant',
        content: response.answer,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        referencedMeetings: response.referenced_meetings,
      };

      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const errorMsg: MessageItem = {
        id: `err-${Date.now()}`,
        role: 'assistant',
        content: '⚠️ I encountered an issue analyzing the dashboard data. Please verify the local LLM server is accessible or try again.',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        isError: true,
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClearHistory = () => {
    setMessages([
      {
        id: 'welcome-cleared',
        role: 'assistant',
        content: 'Conversation history cleared. Ask me anything about your hospital meetings, bottlenecks, or decisions.',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      },
    ]);
  };

  const renderSimpleMarkdown = (text: string) => {
    // Basic formatting: bold, bullets, newlines
    const lines = text.split('\n');
    return (
      <div className="space-y-1.5 leading-relaxed text-xs">
        {lines.map((line, idx) => {
          const trimmed = line.trim();
          if (!trimmed) {
            return <div key={idx} className="h-1" />;
          }

          // Header
          if (trimmed.startsWith('### ')) {
            return (
              <h4 key={idx} className="font-bold text-slate-900 text-xs mt-2 mb-1 flex items-center gap-1.5">
                {trimmed.replace('### ', '')}
              </h4>
            );
          }

          // Bullet list item
          if (trimmed.startsWith('* ') || trimmed.startsWith('- ')) {
            const rawContent = trimmed.substring(2);
            return (
              <div key={idx} className="flex items-start space-x-1.5 pl-1.5">
                <span className="text-medpark-600 font-bold">•</span>
                <span className="flex-1" dangerouslySetInnerHTML={{ __html: formatInline(rawContent) }} />
              </div>
            );
          }

          // Blockquote / Tip
          if (trimmed.startsWith('> ')) {
            return (
              <div
                key={idx}
                className="pl-2.5 py-1 border-l-2 border-medpark-500 bg-medpark-50/60 rounded-r text-[11px] text-slate-700 italic my-1"
                dangerouslySetInnerHTML={{ __html: formatInline(trimmed.replace('> ', '')) }}
              />
            );
          }

          return (
            <p key={idx} dangerouslySetInnerHTML={{ __html: formatInline(trimmed) }} />
          );
        })}
      </div>
    );
  };

  const formatInline = (str: string) => {
    return str
      .replace(/\*\*(.*?)\*\*/g, '<strong class="font-semibold text-slate-900">$1</strong>')
      .replace(/\*(.*?)\*/g, '<em class="italic">$1</em>')
      .replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 bg-slate-100 rounded text-[11px] font-mono text-medpark-700">$1</code>');
  };

  // 1. Minimized / Closed Launcher Button
  if (!isOpen) {
    return (
      <aside aria-label="Executive Intelligence Assistant Launcher" className="fixed bottom-6 right-6 z-50">
        <button
          onClick={() => {
            setIsOpen(true);
            setIsMinimized(false);
          }}
          className="group relative flex items-center space-x-2.5 px-4 py-3 bg-gradient-to-r from-medpark-600 to-medpark-700 hover:from-medpark-700 hover:to-medpark-800 text-white rounded-full shadow-lg hover:shadow-xl transition-all duration-200 transform hover:-translate-y-0.5 focus:outline-none focus:ring-4 focus:ring-medpark-500/30"
          title="Open Medora Executive Intelligence Assistant"
        >
          <div className="relative">
            <Bot className="w-5 h-5 text-white" />
            <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-emerald-400 border-2 border-white rounded-full animate-pulse" />
          </div>
          <span className="text-xs font-bold tracking-wide">Ask Assistant</span>
          <Sparkles className="w-3.5 h-3.5 text-amber-300 animate-spin-slow opacity-80 group-hover:opacity-100" />
        </button>
      </aside>
    );
  }

  // 2. Open / Minimized State
  return (
    <aside aria-label="Executive Intelligence Assistant" className="fixed bottom-6 right-6 z-50 flex flex-col items-end">
      {/* Drawer Window */}
      <div
        className={`w-[440px] max-w-[calc(100vw-32px)] bg-white rounded-3xl border border-slate-200/90 shadow-2xl overflow-hidden transition-all duration-300 flex flex-col ${
          isMinimized ? 'h-16' : 'h-[620px] max-h-[85vh]'
        }`}
      >
        {/* Drawer Header */}
        <div className="p-3.5 bg-gradient-to-r from-slate-900 to-slate-800 text-white flex items-center justify-between flex-shrink-0 border-b border-slate-700/60 select-none">
          <div className="flex items-center space-x-2.5 min-w-0">
            <div className="w-8 h-8 rounded-xl bg-medpark-600/30 border border-medpark-500/40 flex items-center justify-center flex-shrink-0 text-medpark-400">
              <Bot className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center space-x-1.5">
                <h3 className="text-xs font-bold text-white truncate">Medora Intelligence</h3>
                <span className="px-1.5 py-0.2 text-[9px] font-bold uppercase rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                  Air-gapped
                </span>
              </div>
              <p className="text-[10px] text-slate-400 truncate">Council outcomes, lagging tasks & metrics</p>
            </div>
          </div>

          <div className="flex items-center space-x-1">
            <button
              onClick={handleClearHistory}
              title="Reset conversation"
              className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setIsMinimized(!isMinimized)}
              title={isMinimized ? 'Expand' : 'Minimize'}
              className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
            >
              <Minus className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setIsOpen(false)}
              title="Close Assistant"
              className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-slate-800 rounded-lg transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Content Body (Only when not minimized) */}
        {!isMinimized && (
          <>
            {/* Scrollable Messages Container */}
            <div className="flex-1 p-4 overflow-y-auto space-y-3.5 bg-slate-50/50">
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}
                >
                  <div className="flex items-center space-x-1 text-[10px] text-slate-400 mb-1 px-1">
                    {msg.role === 'user' ? (
                      <>
                        <span>You</span>
                        <span>•</span>
                        <span>{msg.timestamp}</span>
                      </>
                    ) : (
                      <>
                        <Sparkles className="w-2.5 h-2.5 text-medpark-600" />
                        <span>Executive AI</span>
                        <span>•</span>
                        <span>{msg.timestamp}</span>
                      </>
                    )}
                  </div>

                  <div
                    className={`p-3.5 rounded-2xl max-w-[90%] shadow-xs ${
                      msg.role === 'user'
                        ? 'bg-medpark-600 text-white rounded-tr-none text-xs font-medium'
                        : msg.isError
                        ? 'bg-rose-50 border border-rose-200 text-rose-900 rounded-tl-none'
                        : 'bg-white border border-slate-200/90 text-slate-800 rounded-tl-none'
                    }`}
                  >
                    {msg.role === 'user' ? (
                      <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                    ) : (
                      renderSimpleMarkdown(msg.content)
                    )}

                    {/* Referenced Meetings Chips */}
                    {msg.referencedMeetings && msg.referencedMeetings.length > 0 && (
                      <div className="mt-2.5 pt-2 border-t border-slate-100 flex flex-wrap gap-1.5">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600 w-full mb-0.5">
                          Referenced Sessions:
                        </span>
                        {msg.referencedMeetings.map((rm) => (
                          <button
                            key={rm.id}
                            onClick={() => {
                              if (onNavigateToMeeting) {
                                onNavigateToMeeting(rm.id);
                              }
                            }}
                            className="inline-flex items-center space-x-1 px-2 py-1 rounded bg-slate-100 hover:bg-medpark-50 hover:text-medpark-700 border border-slate-200 text-[10px] font-medium text-slate-700 transition-colors"
                            title="Open session workspace"
                          >
                            <Calendar className="w-2.5 h-2.5 text-slate-400" />
                            <span className="truncate max-w-[130px]">{rm.title}</span>
                            <ExternalLink className="w-2.5 h-2.5 text-slate-400 ml-0.5" />
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {isLoading && (
                <div className="flex flex-col items-start space-y-1">
                  <div className="flex items-center space-x-1 text-[10px] text-slate-400 px-1">
                    <Sparkles className="w-2.5 h-2.5 text-medpark-600" />
                    <span>Analyzing hospital database...</span>
                  </div>
                  <div className="p-3 bg-white border border-slate-200 rounded-2xl rounded-tl-none flex items-center space-x-2 text-xs text-slate-600 shadow-xs">
                    <Loader2 className="w-4 h-4 animate-spin text-medpark-600" />
                    <span>Reviewing decisions, tasks, and meeting dates...</span>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Quick Suggestions Pills (when not currently loading) */}
            <div className="p-2.5 bg-slate-100/70 border-t border-slate-200/80 overflow-x-auto flex items-center space-x-1.5 scrollbar-thin">
              {QUICK_PROMPTS.map((qp, idx) => {
                const Icon = qp.icon;
                return (
                  <button
                    key={idx}
                    disabled={isLoading}
                    onClick={() => handleSendMessage(qp.query)}
                    className="inline-flex items-center space-x-1.5 px-2.5 py-1 bg-white hover:bg-medpark-50 hover:text-medpark-700 hover:border-medpark-300 border border-slate-200 rounded-full text-[11px] font-semibold text-slate-600 whitespace-nowrap transition-colors shadow-2xs disabled:opacity-50"
                  >
                    <Icon className="w-3 h-3 text-medpark-600 flex-shrink-0" />
                    <span>{qp.label}</span>
                  </button>
                );
              })}
            </div>

            {/* Input Bar */}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSendMessage();
              }}
              className="p-3 bg-white border-t border-slate-200 flex items-center space-x-2"
            >
              <input
                ref={inputRef}
                type="text"
                value={inputQuery}
                onChange={(e) => setInputQuery(e.target.value)}
                placeholder="Ask about meetings, lagging tasks, owners..."
                disabled={isLoading}
                className="flex-1 text-xs px-3 py-2.5 bg-slate-50 border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-medpark-500/40 focus:border-medpark-500 disabled:opacity-50 placeholder:text-slate-400"
              />
              <button
                type="submit"
                disabled={!inputQuery.trim() || isLoading}
                className="p-2.5 bg-medpark-600 hover:bg-medpark-700 text-white rounded-xl disabled:opacity-40 disabled:hover:bg-medpark-600 transition-colors shadow-xs focus:outline-none focus:ring-2 focus:ring-medpark-500/40"
                title="Send query"
              >
                {isLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
              </button>
            </form>
          </>
        )}
      </div>
    </aside>
  );
};

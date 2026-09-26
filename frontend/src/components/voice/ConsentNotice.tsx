import React from 'react';
import { ShieldCheck } from 'lucide-react';

// The statement the person agrees to when enrolling. Its version travels with the consent record
// (ConsentRecord.statement_version); bump the version whenever a single word below changes.
export const CONSENT_STATEMENT_VERSION = 'v1';

export const CONSENT_STATEMENT_EN =
  'I agree that Medora stores a voiceprint of my voice - a numeric template computed from the ' +
  'samples I record here - together with those samples, on this hospital\'s local server only. ' +
  'The voiceprint is used for one purpose: to suggest my name to a human reviewer next to what I ' +
  'said in recorded meetings. A suggestion never appears in any document until a reviewer confirms ' +
  'it. Nothing leaves this server. I can withdraw at any time from the People & Voices page; ' +
  'withdrawal deletes my voiceprint and samples immediately. Names a reviewer has already confirmed ' +
  'on past meeting minutes are kept, because they are part of signed records. Only I can enroll my ' +
  'own voice; nobody can be enrolled from a meeting recording.';

export const CONSENT_STATEMENT_RO =
  'Sunt de acord ca Medora să stocheze o amprentă vocală a vocii mele - un șablon numeric calculat ' +
  'din mostrele pe care le înregistrez aici - împreună cu aceste mostre, exclusiv pe serverul local ' +
  'al spitalului. Amprenta vocală are un singur scop: să propună numele meu unui revizor uman în ' +
  'dreptul a ceea ce am spus în ședințele înregistrate. O propunere nu apare în niciun document ' +
  'până când un revizor nu o confirmă. Nimic nu părăsește acest server. Îmi pot retrage acordul ' +
  'oricând din pagina People & Voices; retragerea șterge imediat amprenta vocală și mostrele. ' +
  'Numele deja confirmate de un revizor în procesele-verbale ale ședințelor anterioare se păstrează, ' +
  'deoarece fac parte din documente semnate. Doar eu îmi pot înregistra propria voce; nimeni nu ' +
  'poate fi înregistrat dintr-o înregistrare a unei ședințe.';

export const CONSENT_STATEMENT_RU =
  'Я согласен(на) с тем, что Medora хранит отпечаток моего голоса - числовой шаблон, вычисленный ' +
  'из записанных здесь образцов, - вместе с самими образцами, только на локальном сервере ' +
  'больницы. Отпечаток голоса используется с одной целью: предлагать моё имя рецензенту рядом с ' +
  'тем, что я сказал(а) на записанных совещаниях. Предложение не попадает ни в один документ, пока ' +
  'рецензент его не подтвердит. Ничто не покидает этот сервер. Я могу отозвать согласие в любой ' +
  'момент на странице People & Voices; отзыв немедленно удаляет отпечаток голоса и образцы. Имена, ' +
  'уже подтверждённые рецензентом в протоколах прошлых совещаний, сохраняются, поскольку являются ' +
  'частью подписанных документов. Только я могу зарегистрировать свой голос; никого нельзя ' +
  'зарегистрировать из записи совещания.';

interface ConsentNoticeProps {
  // compact = one language (English) for cards; full = all three, for the enrollment gate.
  variant?: 'full' | 'compact';
  className?: string;
}

// Fixed, versioned consent wording. Rendered verbatim: no summarising, no paraphrase, no per-person
// edits, so the stored statement_version always means the same text.
export const ConsentNotice: React.FC<ConsentNoticeProps> = ({ variant = 'full', className = '' }) => {
  return (
    <section
      aria-labelledby="consent-notice-title"
      className={`rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3 ${className}`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center space-x-2">
          <ShieldCheck className="w-4 h-4 text-emerald-600 flex-shrink-0" aria-hidden="true" />
          <h4 id="consent-notice-title" className="text-xs font-bold uppercase tracking-wider text-slate-700">
            Voice enrollment consent
          </h4>
        </div>
        <span className="text-[10px] font-mono font-semibold text-slate-500 bg-white border border-slate-200 rounded px-1.5 py-0.5">
          statement {CONSENT_STATEMENT_VERSION}
        </span>
      </div>

      <p lang="en" className="text-xs text-slate-700 leading-relaxed">
        {CONSENT_STATEMENT_EN}
      </p>

      {variant === 'full' && (
        <>
          <p lang="ro" className="text-xs text-slate-600 leading-relaxed border-t border-slate-200 pt-3">
            <span className="font-bold text-slate-500 mr-1">RO</span>
            {CONSENT_STATEMENT_RO}
          </p>
          <p lang="ru" className="text-xs text-slate-600 leading-relaxed border-t border-slate-200 pt-3">
            <span className="font-bold text-slate-500 mr-1">RU</span>
            {CONSENT_STATEMENT_RU}
          </p>
        </>
      )}
    </section>
  );
};

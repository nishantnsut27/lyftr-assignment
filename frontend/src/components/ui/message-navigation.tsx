import { Tooltip } from '@base-ui/react/tooltip';
import { MessageSquare } from 'lucide-react';
import type { ChatTurn } from '@/types';

export function MessageNavigation({
  turns,
  onNavigate,
}: {
  turns: ChatTurn[];
  onNavigate: (id: string) => void;
}) {
  if (!turns.length) return null;
  return (
    <Tooltip.Provider delay={150}>
      <nav className="message-navigation" aria-label="Message navigation">
        <span className="navigation-label" aria-hidden="true">
          <MessageSquare size={14} />
        </span>
        <div className="navigation-markers">
          {turns.map((turn, index) => (
            <Tooltip.Root key={turn.id}>
              <Tooltip.Trigger
                className="navigation-marker"
                aria-label={`Jump to message ${index + 1}: ${turn.request.message.slice(0, 80)}`}
                onClick={() => onNavigate(turn.id)}
              >
                <span aria-hidden="true" />
              </Tooltip.Trigger>
              <Tooltip.Portal>
                <Tooltip.Positioner side="right" sideOffset={12}>
                  <Tooltip.Popup className="navigation-preview">
                    <span>Message {index + 1}</span>
                    <p>
                      {Array.from(turn.request.message).slice(0, 160).join('')}
                    </p>
                  </Tooltip.Popup>
                </Tooltip.Positioner>
              </Tooltip.Portal>
            </Tooltip.Root>
          ))}
        </div>
      </nav>
    </Tooltip.Provider>
  );
}

import { useState } from 'react'
import { BrainCircuit, ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'

/** 模型的思考过程（reasoning part），默认折叠。 */
export function ReasoningBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={cn('reasoning-block', open && 'open')}>
      <button className="reasoning-toggle" onClick={() => setOpen((o) => !o)}>
        <BrainCircuit size={13} />
        <span>思考过程</span>
        <ChevronDown size={13} className={cn('chev', open && 'flip')} />
      </button>
      {open && <div className="reasoning-body">{text}</div>}
    </div>
  )
}

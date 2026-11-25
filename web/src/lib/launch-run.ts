import {platformRead, type Settings} from './console-types';
type Launch = {profile: string; run_id: string; settings: Settings; start: boolean};
type Sender = (body: Record<string,unknown>) => Promise<unknown>;
const send: Sender = body => platformRead('',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
/** Start only after configuration was persisted. Never auto-retry a creation. */
export async function launchRun(input: Launch, onCreated: () => Promise<void>, request: Sender = send) {
  await request({action:'create',profile:input.profile,run_id:input.run_id,settings:input.settings});
  await onCreated();
  if (input.start) await request({action:'start',run_id:input.run_id});
}

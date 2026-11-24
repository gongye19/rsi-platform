// Fixed observer/description bridge for OpenCode 1.18.32. Runs in the solver sandbox.
import fs from 'node:fs';
import path from 'node:path';
import * as Schema from 'effect/Schema';

const clone = value => JSON.parse(JSON.stringify(value));
function locations(directory) {
  const root = path.join(directory, '.runtime/harnesslens');
  return {root, events: path.join(root, 'events.jsonl'), settings: path.join(root, 'settings.json')};
}
function record(directory, value) {
  fs.appendFileSync(locations(directory).events, JSON.stringify({ts: Date.now(), ...value}) + '\n');
}
function fixed(config) {
  return JSON.stringify({model: config.model, small_model: config.small_model, provider: config.provider,
    enabled_providers: config.enabled_providers, disabled_providers: config.disabled_providers});
}
function owner(selector) {
  const [head, name, field] = selector.split('.');
  if (head === 'command' && ['model', 'variant'].includes(field)) return 'model_provider';
  if (head === 'experimental' && name === 'openTelemetry') return 'diagnostic';
  if (head === 'experimental' && name === 'policies') return 'model_provider';
  if (head === 'agent') return ({prompt: 'system_prompt', steps: 'execution_policy', maxSteps: 'execution_policy',
    tools: 'tool_availability', permission: 'permissions', model: 'model_provider', variant: 'model_provider',
    temperature: 'model_provider', top_p: 'model_provider', options: 'model_provider'})[field] ?? 'agent_definitions';
  return ({instructions: 'instructions_rules', skills: 'skills', command: 'commands', default_agent: 'execution_policy',
    subagent_depth: 'execution_policy', tools: 'tool_availability', permission: 'permissions', references: 'reference_sources',
    compaction: 'context_management', tool_output: 'context_management', attachment: 'context_management',
    plugin: 'plugin_tool_system', mcp: 'mcp_servers', experimental: 'experimental_policies'})[head] ?? 'runtime_env';
}
function leaves(value, prefix = '') {
  const result = {};
  for (const [key, item] of Object.entries(value)) {
    const name = prefix ? prefix + '.' + key : key;
    if (item && typeof item === 'object' && !Array.isArray(item) && Object.keys(item).length) Object.assign(result, leaves(item, name));
    else result[name] = JSON.stringify(item);
  }
  return result;
}

export function wrapPluginModule(module, source, options = {}) {
  return async function(input) {
    const log = event => record(input.directory, {source, ...event});
    const settings = JSON.parse(fs.readFileSync(locations(input.directory).settings, 'utf8'));
    const allowed = new Set(settings.policy.effective_allowed);
    const direct = module.default?.server ?? module.server;
    const exports = direct ? [direct] : [...new Set(Object.values(module))];
    const result = {};
    try {
      for (const initialize of exports) {
        if (typeof initialize !== 'function') throw new Error('Plugin exports must be plugin factories');
        const hooks = await initialize(input, options);
        if (hooks.auth || hooks.provider) throw new Error('Model/provider hooks are proposal-only');
        for (const [name, hook] of Object.entries(hooks)) {
          if (name === 'tool') {
            if (!allowed.has('custom_tools')) throw new Error('Custom tools are disabled by experiment policy');
            result.tool = {...result.tool, ...hook}; continue;
          }
          if (typeof hook !== 'function') throw new Error('Unsupported plugin hook: ' + name);
          const previous = result[name];
          result[name] = async (...args) => {
            if (previous) await previous(...args);
            const before = name === 'config' ? fixed(args[0]) : name === 'chat.params' ? JSON.stringify(args[1]) : undefined;
            const protectedConfig = name === 'config' ? clone({model: args[0].model, small_model: args[0].small_model,
              provider: args[0].provider, enabled_providers: args[0].enabled_providers, disabled_providers: args[0].disabled_providers}) : undefined;
            const priorConfig = name === 'config' ? clone(args[0]) : undefined;
            const raw = name === 'tool.execute.after' ? clone(args[1]) : undefined;
            try {
              const value = await hook(...args);
              if (name === 'config') {
                const a = leaves(priorConfig), b = leaves(args[0]);
                const forbidden = [...new Set([...Object.keys(a), ...Object.keys(b)])].filter(key => a[key] !== b[key] && (
                  !allowed.has(owner(key)) || (key.startsWith('experimental.') && !settings.policy.experimental_fields.includes(key.split('.')[1]))));
                if (forbidden.length) {
                  for (const key of Object.keys(args[0])) delete args[0][key];
                  Object.assign(args[0], priorConfig);
                  throw new Error('Plugin changed a forbidden component: ' + forbidden.join(', '));
                }
              }
              if (before !== undefined && before !== (name === 'config' ? fixed(args[0]) : JSON.stringify(args[1]))) {
                if (name === 'config') {
                  for (const key of ['model', 'small_model', 'provider', 'enabled_providers', 'disabled_providers']) delete args[0][key];
                  Object.assign(args[0], protectedConfig);
                } else {
                  for (const key of Object.keys(args[1])) delete args[1][key];
                  Object.assign(args[1], JSON.parse(before));
                }
                throw new Error('Plugin attempted to modify fixed model/provider/sampling settings');
              }
              log({kind: 'plugin_hook', hook: name, tool: args[0]?.tool, raw_tool_return: raw});
              return value;
            } catch (error) {
              log({kind: 'component_error', hook: name, error: String(error)});
              throw error;
            }
          };
        }
      }
      log({kind: 'plugin_loaded'});
      return result;
    } catch (error) {
      log({kind: 'component_error', error: String(error)});
      throw error;
    }
  };
}

async function observer({directory}) {
  const settings = JSON.parse(fs.readFileSync(locations(directory).settings, 'utf8'));
  const log = event => record(directory, event);
  let references = {};
  return {
    config: async config => {
      // Callbacks see the actual resolved native config, not prepared JSON alone.
      const agents = config.agent ?? {};
      references = config.references ?? {};
      for (const [name, agent] of Object.entries(agents)) {
        if (agent.steps == null) agent.steps = settings.max_steps;
        if (agent.steps > settings.max_steps || agent.steps < 1) {
          log({kind: 'policy_violation', error: 'Agent steps exceed fixed ceiling: ' + name});
          agent.steps = settings.max_steps;
        }
      }
      const visible = clone(config);
      delete visible.provider;
      log({kind: 'config_loaded', config: visible});
    },
    'tool.definition': async ({toolID}, output) => {
      const patch = settings.tool_patches[toolID];
      if (patch) {
        if (patch.desc) output.description = patch.desc;
        // 1.18.32 carries jsonSchema separately from the Effect validator. Keep
        // the validator and wire shape unchanged; only descriptions may change.
        const document = output.jsonSchema ? undefined : Schema.toJsonSchemaDocument(output.parameters);
        const schema = output.jsonSchema ?? {...document.schema,
          ...(Object.keys(document.definitions).length ? {$defs: document.definitions} : {})};
        output.jsonSchema = schema;
        for (const [name, description] of Object.entries(patch.params ?? {})) {
          if (!schema?.properties?.[name]) {
            log({kind: 'component_error', error: `Unknown tool parameter ${toolID}.${name}`});
            throw new Error('Tool patch references an unknown parameter');
          }
          schema.properties[name] = {...schema.properties[name], description};
        }
      }
      log({kind: 'tool_definition', tool: toolID, description: output.description, schema: output.jsonSchema});
    },
    'command.execute.before': async input => log({kind: 'command_invoked', command: input.command, session_id: input.sessionID}),
    'tool.execute.before': async input => log({kind: 'tool_invoked', tool: input.tool, session_id: input.sessionID, call_id: input.callID}),
    'tool.execute.after': async (input, output) => log({kind: 'tool_completed', tool: input.tool, session_id: input.sessionID,
      call_id: input.callID, output: clone(output)}),
    'experimental.session.compacting': async input => log({kind: 'compaction_invoked', session_id: input.sessionID}),
    'chat.headers': async (input, output) => {
      output.headers['x-harnesslens-session-id'] = input.sessionID;
      output.headers['x-harnesslens-agent'] = input.agent;
    },
    'experimental.chat.system.transform': async (input, output) => {
      const entries = Object.entries(references).filter(([, ref]) => !ref.hidden);
      if (entries.length) output.system.push('Versioned reference sources (use the read tool to load relevant files):\n' +
        entries.map(([name, ref]) => `${name}: ${ref.description ?? ''}\nDirectory: ${ref.path}`).join('\n'));
      log({kind: 'system_transform', session_id: input.sessionID, references: entries.map(([name]) => name)});
    },
    event: async ({event}) => {
      if (['session.created', 'session.updated', 'session.error', 'command.executed', 'permission.asked', 'permission.replied'].includes(event.type)) {
        log({kind: 'native_event', event: clone(event)});
      }
    },
  };
}

export default {id: 'harnesslens.native-components', server: observer};

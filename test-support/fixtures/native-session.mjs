// Test-only bootstrap: use the native session API and retain its history on reboot.
import {randomUUID} from 'node:crypto';
export const name='monitor-system-test-session';
export const inject=['sessionController'];
export async function apply(ctx,config) {
  const {sessionId}=await ctx.sessionController.create({sessionId:config.sessionId,cwd:config.cwd});
  await ctx.sessionController.selectModel({sessionId,provider:'deepseek-official',model:'test-model',reasoningEffort:'high'});
  await ctx.sessionController.prompt({requestId:randomUUID(),sessionId,mode:'queue',content:[{type:'text',text:'TEST_NATIVE_BOOT:'+randomUUID()}],clientTimeZone:'Asia/Shanghai'},AbortSignal.timeout(30000));
}

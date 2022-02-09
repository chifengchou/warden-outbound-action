import OutboundStack from "./outboundStack";
import CicdStack, { stages as cicdStages } from "./cicdStack";
import * as sst from "@serverless-stack/resources";



export default function main(app: sst.App): void {
  console.log(`stage=${app.stage}, local=${app.local}`)

  if (cicdStages.indexOf(app.stage) !== -1) {
    // In any of STAGES, we assume the intention is to deploy CI/CD.
    if (!app.local) {
      console.log(`Prepare pipeline for ${app.stage}`);
      new CicdStack(app, "Pipeline", {
        stackName: `${app.stage}-tgr-warden-outbound-pipeline`
      })
    } else {
      throw new Error(`sst start for ${app.stage} is not allowed`);
    }
  } else {
    console.log(`Prepare stack for ${app.stage}`)
    new OutboundStack(app, "Stack", {
      stackName: `${app.stage}-tgr-warden-outbound-stack`
    });
  }
}

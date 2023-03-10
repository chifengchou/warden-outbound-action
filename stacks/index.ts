import OutboundStack from "./outboundStack";
import CicdStack from "./cicdStack";
import * as sst from "@serverless-stack/resources";
import {Config} from "./config";

const tags = {
  "horangi:system": "warden-platform",
  "horangi:application-owner": "engineering",
  "horangi:cost-center": "warden-platform",
  "horangi:environment": "dev",
}

export default function main(app: sst.App): void {
  // cicdStages are reserved stages for deploying CI/CD pipeline.
  // Other stages are for deploying application stack.
  const cicdStages = Config.getCicdStageNames()
  if (cicdStages.indexOf(app.stage) !== -1) {
    // CICD can't be deployed to local.
    if (!app.local) {
      console.log(`Prepare pipeline for ${app.stage}`);
      tags["horangi:environment"] = app.stage
      new CicdStack(app, "Pipeline", {
        stackName: `${app.stage}-tgr-warden-outbound-pipeline`,
        tags
      })
    } else {
      throw new Error(`Local deployment(sst start) for ${app.stage} is not allowed`);
    }
  } else {
    console.log(`Prepare stack for ${app.stage}`)
    new OutboundStack(app, "Stack", {
      stackName: `${app.stage}-tgr-warden-outbound-stack`,
      tags,
    });
  }
}

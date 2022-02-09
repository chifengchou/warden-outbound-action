import * as sst from "@serverless-stack/resources";
import {CodeBuildStep, CodePipeline, CodePipelineSource, ShellStep} from "aws-cdk-lib/pipelines";
import {Effect, PolicyStatement} from "aws-cdk-lib/aws-iam";
import {Stage, StageProps} from "aws-cdk-lib";
import OutboundStack from "./outboundStack";

export const stages = ["dev", "staging", "prod"]

interface GitConnectionConfig {
  github_owner: string
  github_repo: string
  git_branch: string
  github_connection_arn: string
  github_secret_name: string
}

const cicdConfig: Record<string, GitConnectionConfig> = {
  dev: {
    github_owner: "horangi-ir",
    github_repo: "tgr-warden-outbound",
    //git_branch: "develop",
    git_branch: "feature/cicd",
    github_connection_arn: "arn:aws:codestar-connections:ap-southeast-1:410801124909:connection/a6f85a35-6448-48ba-ad25-46bc9bb8caeb",
    github_secret_name: "tgr-dev-1-platform-github-ssh",
  },
  staging: {
    github_owner: "horangi-ir",
    github_repo: "tgr-warden-outbound",
    git_branch: "release/candidate",
    github_connection_arn: "",
    github_secret_name: "tgr-dev-1-platform-github-ssh",
  },
  prod: {
    github_owner: "horangi-ir",
    github_repo: "tgr-warden-outbound",
    git_branch: "master",
    github_connection_arn: "arn:aws:codestar-connections:ap-southeast-1:410801124909:connection/a6f85a35-6448-48ba-ad25-46bc9bb8caeb",
    github_secret_name: "tgr-dev-1-platform-github-ssh",
  },
};


export default class CicdStack extends sst.Stack {
  constructor(scope: sst.App, id: string, props?: sst.StackProps) {
    super(scope, id, props);

    const prefix = `${scope.stage}-tgr-warden-outbound`;
    const config: GitConnectionConfig = cicdConfig[scope.stage]
    const input = CodePipelineSource.connection(
      `${config.github_owner}/${config.github_repo}`,
      `${config.git_branch}`,
      {
        connectionArn: config.github_connection_arn,
      }
    );
    const rolePolicyStatements = [
      new PolicyStatement({
        actions: ["secretsmanager:GetSecretValue"],
        effect: Effect.ALLOW,
        resources: [
          `arn:aws:secretsmanager:${scope.region}:${scope.account}:secret:${config.github_secret_name}*`
        ],
      }),
      new PolicyStatement({
        actions: ["cloudformation:DescribeStacks"],
        effect: Effect.ALLOW,
        resources: [
          // FIXME: should only be ${stage}-tgr-warden-outbound-Pipeline
          `arn:aws:cloudformation:ap-southeast-1:410801124909:stack/*`,
        ],
      }),
      new PolicyStatement({
        actions: ["ssm:GetParameter"],
        effect: Effect.ALLOW,
        resources: ["*"],
      }),
      new PolicyStatement({
        actions: ["ec2:Describe*"],
        effect: Effect.ALLOW,
        resources: ["*"],
      }),
    ];
    const synth = new CodeBuildStep("Build", {
      projectName: `${prefix}-build`,
      input,
      //env: {}
      installCommands: [
        // Retrieving submodules
        //"mkdir -p /root/.ssh/",
        //"touch /root/.ssh/known_hosts",
        //"ssh-keyscan github.com >> /root/.ssh/known_hosts",
        //`aws secretsmanager get-secret-value --secret-id ${config.github_secret_name} | jq -r ".SecretString" > /root/.ssh/temp_rsa',
        //"chmod 400 /root/.ssh/temp_rsa`,
        //'eval "$(ssh-agent -s)" && ssh-add /root/.ssh/temp_rsa',
        //"git submodule update --init --recursive",
        // Testing
        // Building
        "npm install",
      ],
      commands: [
        `npx sst deploy --stage ${scope.stage}`
      ],
      primaryOutputDirectory: ".build/cdk.out",
      rolePolicyStatements,
    })
    const pipeline = new CodePipeline(this, "Pipeline", {
      pipelineName: `${prefix}-pipeline`,
      synth,
      dockerEnabledForSynth: true
    })
    pipeline.addStage(new OutboundStage(this, `${prefix}-stage`))
  }
}


class OutboundStage extends Stage {
  constructor(scope: sst.Stack, id: string, props?: StageProps) {
    super(scope, id, props);
    // FIXME: Lack of support of CodePipeline in sst out-of-box. We pass in a Stage where sst.App is required.
    //  Potentially it'll break. Note that sst.App <: cdk.App <: Stage.
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    new OutboundStack(this, "Stack");
  }
}
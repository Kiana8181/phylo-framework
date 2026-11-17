import Link from "next/link";
import { ScrollText } from "lucide-react";
import { ContactLink, LegalDocument, type LegalSection } from "@/components/legal/LegalDocument";
import { LEGAL } from "@/lib/legal";

const GOOGLE_TERMS_URL = "https://policies.google.com/terms";

const HIGHLIGHTS = [
  "The service is for research. Do not use its results to make clinical or diagnostic decisions.",
  "Your data stays yours. Upload only data you are allowed to use, and remove anything that directly identifies a person.",
  `Download what you need: results are deleted ${LEGAL.resultRetentionDays} days after a run ends, datasets ${LEGAL.datasetRetentionDays} days after upload unless you renew them, and backups are not guaranteed.`,
  "The service is provided as is, on shared computing resources with usage limits.",
];

const SECTIONS: LegalSection[] = [
  {
    id: "agreement",
    title: "Agreeing to these terms",
    body: (
      <>
        <p>
          These terms govern your use of the {LEGAL.appName} service hosted on this website, operated by {LEGAL.operator} (“we”, “us”). By
          creating an account, signing in, or otherwise using the service, you agree to them. If you
          do not agree, do not use the service.
        </p>
        <p>
          If you use the service for an institution, you confirm that you are allowed to accept these
          terms on its behalf. Our <Link href="/privacy">Privacy Policy</Link> explains how we handle
          personal data.
        </p>
      </>
    ),
  },
  {
    id: "service",
    title: "The service",
    body: (
      <>
        <p>
          {LEGAL.appName} lets you upload B-cell receptor sequence datasets, reconstruct lineage trees
          with the Dowser, GCtree, BrepPhylo and ClonalTree methods, and compare the results. It is
          currently free of charge.
        </p>
        <p>
          We may change, suspend or end any part of the service, including its methods and limits.
          When a change significantly affects you, we will try to give reasonable notice.
        </p>
      </>
    ),
  },
  {
    id: "research-use",
    title: "Research use only",
    body: (
      <p>
        The service is a research tool. It is not a medical device, and its results must not be used
        to diagnose, treat or make decisions about any patient. Reconstructed trees are statistical
        inferences that depend on your data and settings, so you are responsible for checking them
        before you rely on or publish them.
      </p>
    ),
  },
  {
    id: "accounts",
    title: "Your account",
    body: (
      <>
        <p>
          You can sign up with an email address or sign in with Google. If you sign in with Google,
          Google’s{" "}
          <a href={GOOGLE_TERMS_URL} target="_blank" rel="noopener noreferrer">
            Terms of Service
          </a>{" "}
          also apply to your Google account.
        </p>
        <ul>
          <li>Give a real email address that you control, and use one account per person.</li>
          <li>Keep your sign-in details private. Do not share your account.</li>
          <li>
            You are responsible for what happens under your account. Tell us promptly at{" "}
            <ContactLink /> if you suspect someone else has used it.
          </li>
          <li>You must be at least 16 years old to use the service.</li>
        </ul>
      </>
    ),
  },
  {
    id: "your-data",
    title: "Your data",
    body: (
      <>
        <p>
          You keep all rights to the datasets you upload and the results you generate. You give us
          only the permission needed to store and process them to provide the service to you. We claim
          no ownership of them and do not publish them.
        </p>
        <p>By uploading a dataset, you confirm that:</p>
        <ul>
          <li>you have the right to use it in this way;</li>
          <li>
            where it comes from human subjects, you have the consent, ethics approval and other
            permissions that apply to it;
          </li>
          <li>
            you have removed names, medical record numbers, contact details and anything else in the
            files that directly identifies a person.
          </li>
        </ul>
        <p>
          Do not use the service for data that the law or your institution requires to be kept in a
          specially certified or access-controlled environment. It is not designed for such data.
        </p>
      </>
    ),
  },
  {
    id: "acceptable-use",
    title: "Acceptable use",
    body: (
      <>
        <p>
          The server is shared with other researchers, so please use it fairly. You must not:
        </p>
        <ul>
          <li>bypass or try to bypass quotas, rate limits, sign-in protection or access controls;</li>
          <li>access, or try to access, other users’ accounts or data;</li>
          <li>upload malware, or files intended to harm the service or its users;</li>
          <li>probe or attack the service, or disrupt it for others;</li>
          <li>create accounts automatically, or several accounts to get around a limit;</li>
          <li>use the service for anything unlawful or for mining, or other work unrelated to its purpose.</li>
        </ul>
      </>
    ),
  },
  {
    id: "limits",
    title: "Limits, storage and availability",
    body: (
      <>
        <p>
          Use is subject to limits on run frequency, upload size, storage and run time. The current
          limits are shown in the application or reported when you reach them, and we may change them.
          A run may wait in a queue, or be stopped if it exceeds its limits.
        </p>
        <p>
          <strong>Results are deleted {LEGAL.resultRetentionDays} days after a run ends</strong>; the
          date is shown with the run. <strong>Datasets are deleted {LEGAL.datasetRetentionDays} days
          after you upload them</strong> unless you renew them from File management. Renewal is
          offered during the {LEGAL.datasetWarningHours} hours before expiration; that warning period
          is a deployment setting and is not fixed at 24 hours. Removal is permanent. The service
          does not guarantee backups, so keep your own copies of anything important.
        </p>
      </>
    ),
  },
  {
    id: "software",
    title: "Software and third-party methods",
    body: (
      <p>
        The {LEGAL.appName} software is released under the MIT License. These terms cover the hosted
        service, not your rights under that license. The reconstruction methods are independent
        projects with their own licenses and are not covered by the {LEGAL.appName} license. When you
        publish results, please cite the methods you used.
      </p>
    ),
  },
  {
    id: "ending",
    title: "Ending your use",
    body: (
      <>
        <p>
          You may stop using the service at any time. To delete your account and its data, email{" "}
          <ContactLink />, as described in the <Link href="/privacy#your-choices">Privacy Policy</Link>.
        </p>
        <p>
          We may suspend or close an account that breaks these terms or puts the service or its users
          at risk. Where we reasonably can, we will tell you first and give you the chance to download
          your data.
        </p>
      </>
    ),
  },
  {
    id: "warranties",
    title: "Disclaimers and liability",
    body: (
      <>
        <p>
          The service is provided <strong>“as is” and “as available”</strong>, without warranties of
          any kind, including accuracy of results, fitness for a particular purpose and uninterrupted
          availability.
        </p>
        <p>
          To the fullest extent the law allows, we are not liable for indirect or consequential loss,
          or for loss of data, results, research time or opportunity arising from your use of the
          service. Nothing in these terms limits a liability or removes a right that cannot be limited
          or removed under the law that applies to you.
        </p>
      </>
    ),
  },
  {
    id: "changes",
    title: "Changes to these terms",
    body: (
      <p>
        We may update these terms. We will publish the new version here and update its effective date,
        and for significant changes we will try to notify you in advance. If you keep using the service
        after a change takes effect, you accept the updated terms.
      </p>
    ),
  },
  {
    id: "contact",
    title: "Contact",
    body: (
      <p>
        Questions about these terms: {LEGAL.operator}, <ContactLink />.
      </p>
    ),
  },
];

export function TermsDoc() {
  return (
    <LegalDocument
      active="terms"
      icon={ScrollText}
      title="Terms of Service"
      summary={`The rules for using ${LEGAL.appName}: what the service offers, what it asks of you, and the limits of what it promises.`}
      highlights={HIGHLIGHTS}
      sections={SECTIONS}
    />
  );
}

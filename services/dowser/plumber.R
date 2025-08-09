# services/dowser/plumber.R
#* @apiTitle Dowser microservice
#* @apiDescription Build BCR lineage trees with Dowser using example data for now.
library(plumber)
library(jsonlite)
library(dowser)
library(alakazam)
library(ape)
library(tibble)

# ---------- /spec ----------
#* Return JSON Schema for parameters and accepted formats
#* @serializer json
#* @get /spec
function(){
  list(
    id        = "dowser",
    name      = "Dowser",
    version   = as.character(utils::packageVersion("dowser")),
    accepts   = c("text/csv","text/tab-separated-values","application/x-rds","application/x-rda","text/fasta"),
    paramSchema = list(
      `$schema` = "http://json-schema.org/draft-07/schema#",
      type = "object",
      properties = list(
        tree_model = list(enum = c("mp","ml","igphyml"), title="Tree model", default="mp"),
        minseq     = list(type="integer", title="Min seq per clone", default=3),
        nproc      = list(type="integer", title="Threads", default=1)
      ),
      required = list("tree_model")
    ),
    uiHints = list(order = c("tree_model","minseq","nproc"))
  )
}

# helper to write phylo to Newick string
phylo_to_newick <- function(phy) {
  con <- textConnection("out", "w"); on.exit(close(con))
  write.tree(phy, con); out
}

# ---------- /run ----------
#* Build trees (for now uses ExampleAirr; file parsing comes next)
#* @param params:json
#* @serializer json
#* @post /run
function(params="{}"){
  p <- jsonlite::fromJSON(params)
  if (is.null(p$tree_model)) p$tree_model <- "mp"
  if (is.null(p$minseq))     p$minseq     <- 3
  if (is.null(p$nproc))      p$nproc      <- 1

  # Example data shipped with Immcantation packages
  data(ExampleAirr, package="alakazam")
  ExampleAirr <- ExampleAirr[ExampleAirr$clone_id %in% c("3170","3184"),]

  # Prepare clones (AIRR-style input expected)
  clones <- formatClones(ExampleAirr, traits="c_call", minseq=p$minseq)

  # Build trees (max parsimony by default; ML/IgPhyML can be chosen in real runs)
  clones <- getTrees(clones, nproc=p$nproc)  # adds $trees (ape::phylo) per clone

  # Convert trees to Newick
  newicks <- lapply(clones$trees, phylo_to_newick)
  list(
    ok     = TRUE,
    trees  = unname(newicks),
    clones = clones |> as_tibble() |> dplyr::select(clone_id, seqs) |> as.data.frame()
  )
}

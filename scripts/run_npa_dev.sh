#!/bin/bash
#SBATCH --job-name=wu_npa_dev
#SBATCH -n 4
#SBATCH -t 02:00:00
#SBATCH -p gpu_shared
#SBATCH --gres=gpu:1
#SBATCH --mem=60000M


module load pre2019
module load Miniconda3/4.3.27
source activate thesis-user-modelling

workdir=$PWD

cd $workdir/train_scripts

python --version
#srun -n 2 -t 00:30:00 --pty bash -il

data=(  "../datasets/dpg/dev_time_split_most_common/"
        "../datasets/dpg/dev_time_split_random/")

embeddings="../embeddings/cc.nl.300.bin"
train="wu"
eval="wu"
exp_name="dev_vanilla_npa_CE"
n_epochs=2
batch_size=100

SEEDS=(42 113)


echo $exp_name
for datapath in "${data[@]}"
do
echo "$datapath"
for SEED in "${SEDDS[@]}"
do
  #1
  python -u train_npa.py --data_path=$datapath --word_emb_path=$embeddings --exp_name=$exp_name \
  --npa_variant="vanilla" --random_seed=$SEED --n_epochs=$n_epochs --batch_size=$batch_size --train_method=$train

  #2
  python -u train_npa.py --data_path=$datapath --word_emb_path=$embeddings --exp_name=$exp_name \
  --npa_variant="vanilla" --random_seed=$SEED --n_epochs=$n_epochs --batch_size=$batch_size --train_method=$train \
  --eval_method='custom' --lr=0.0001

  #3
    python -u train_npa.py --data_path=$datapath --word_emb_path=$embeddings --exp_name=$exp_name \
  --npa_variant="vanilla" --random_seed=$SEED --n_epochs=$n_epochs --batch_size=$batch_size --train_method=$train \
  --eval_method='custom' --lr=0.00001
done
done
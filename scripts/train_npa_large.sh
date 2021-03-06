#!/bin/bash
#SBATCH --job-name=train_npa_large
#SBATCH -n 8
#SBATCH -t 12:00:00
#SBATCH -p gpu_shared
#SBATCH --gres=gpu:1
#SBATCH --mem=60000M


module load pre2019
module load Miniconda3/4.3.27
source activate thesis-user-modelling

workdir=$PWD

#[ -f /etc/resolv.conf ] && echo "File exists" || echo "File does NOT exist"

cd $workdir/train_scripts

python --version

python -u train_npa.py --data_path="../datasets/dpg/i100k_u50k_s30/" --word_emb_path="../embeddings/cc.nl.300.bin" --test_w_one=1 --exp_name="large"
python -u train_npa.py --data_path="../datasets/dpg/i100k_u50k_s30/" --word_emb_path="../embeddings/cc.nl.300.bin" --weight_decay=0.0001 --test_w_one=1 --exp_name="large-wd1e4"
#python -u train_npa.py --data_path="../datasets/dpg/i100k_u50k_s30/" --word_emb_path="../embeddings/cc.nl.300.bin" --test_w_one=1 --random_seed=13 --exp_name="large"
#python -u train_npa.py --data_path="../datasets/dpg/i100k_u50k_s30/" --word_emb_path="../embeddings/cc.nl.300.bin" --test_w_one=1 --random_seed=102 --exp_name="large"


